"""Validated, read-only server tool. No client-supplied satellite measurements."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from fastapi import HTTPException
from . import service


class VegetationChangeArguments(BaseModel):
    model_config = ConfigDict(extra='forbid')
    zone_id: str = Field(min_length=1, max_length=80, pattern=r'^[a-zA-Z0-9:_-]+$')
    period_start: Literal[2020] = 2020
    period_end: Literal[2026] = 2026
    threshold: float = Field(.3, ge=.1, le=.9, allow_inf_nan=False)


TOOL_DEFINITION = {
    'name': 'get_vegetation_change',
    'description': 'Read verified precomputed Sentinel-2 vegetation change for the selected OSM zone, summer 2020 versus summer 2026. NDVI transitions do not prove tree planting or felling.',
    'parameters': VegetationChangeArguments.model_json_schema(),
}


def get_vegetation_change(arguments: VegetationChangeArguments, selected_zone: dict, language='ru'):
    """Caller must first validate the selected zone geometry with selected_zone_context."""
    if not selected_zone or selected_zone.get('id') != arguments.zone_id:
        raise HTTPException(422, 'Выбранная зона и зона спутникового анализа не совпадают.' if language != 'kk' else 'Таңдалған аумақ пен спутниктік талдау аумағы сәйкес келмейді.')
    result = service.get_vegetation_change(
        zone_id=arguments.zone_id, period_start=arguments.period_start,
        period_end=arguments.period_end, threshold=arguments.threshold, language=language)
    # Keep the actual server numbers and provenance. Strip geometry, assets and unbounded metadata.
    compact = {key: result.get(key) for key in [
        'status', 'reason', 'scope', 'zone_id', 'period_start', 'period_end', 'threshold',
        'dataset_id', 'statistics', 'warnings', 'source']}
    compact['territory'] = {key: result.get('territory', {}).get(key) for key in ('ru', 'kk', 'status')}
    compact['periods'] = {
        str(year): {
            'start': result.get('periods', {}).get(str(year), {}).get('start'),
            'end': result.get('periods', {}).get(str(year), {}).get('end'),
            'scenes': [
                {key: scene.get(key) for key in ('id', 'date', 'cloud_cover', 'source')}
                for scene in result.get('periods', {}).get(str(year), {}).get('scenes', [])[:24]
            ],
        } for year in (2020, 2026)
    }
    # A zone result has scope=zone even when its source is the city dataset.
    # Resolve source coverage from verified server metadata, not selection scope.
    aoi = result.get('aoi') or {}
    city = bool(aoi.get('id') and result.get('coverage'))
    compact['dataset_scope'] = 'administrative_city' if city else 'pavlodar_centre'
    compact['aoi'] = {key: aoi.get(key) for key in ('id', 'name_ru', 'name_kk', 'area_km2', 'source')} if city else None
    coverage_desc = ('The source dataset covers the verified administrative territory of Pavlodar. '
                     'This result describes only the selected zone, not the entire city.') if city else 'The source dataset is a central Pavlodar pilot, not the whole city.'
    compact['interpretation_rules'] = [
        'Use only statistics returned here; status other than ready means no verified numerical comparison.',
        coverage_desc + ' Means and areas use common valid pixels.',
        'NDVI measures probable vegetation including grass and shrubs, not a count of trees.',
        'Possible causes are hypotheses. Neither planting, felling, neglect nor ownership can be proved from NDVI.',
        'Do not change an OSM zone status or claim planting permission. Recommend field inspection before work.',
        'Threshold and source periods must be stated when explaining changes.'
    ]
    return {'name': TOOL_DEFINITION['name'], 'arguments': arguments.model_dump(), 'result': compact}
