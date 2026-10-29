"""Pure raster calculations. Synthetic arrays belong only in tests, never production."""
import warnings
import numpy as np

VALID_SCL = (4, 5, 6)  # vegetation, bare soil, water. SCL is natively 20 m.
NODATA = -9999.0


def quality_mask(scl):
    """Conservative quality: reject cloud, shadow/dark, snow, invalid, unclassified."""
    return np.isin(np.asarray(scl), VALID_SCL)


def calculate_ndvi(red, nir, scl=None):
    red = np.asarray(red, dtype=np.float32)
    nir = np.asarray(nir, dtype=np.float32)
    if red.shape != nir.shape or (scl is not None and np.shape(scl) != red.shape):
        raise ValueError('Raster grids differ')
    valid = np.isfinite(red) & np.isfinite(nir) & (red >= 0) & (nir >= 0) & ((nir + red) > 0)
    if scl is not None:
        valid &= quality_mask(scl)
    result = np.full(red.shape, np.nan, dtype=np.float32)
    np.divide(nir - red, nir + red, out=result, where=valid)
    result[~np.isfinite(result) | (result < -1) | (result > 1)] = np.nan
    return result


def median_composite(stack):
    """Median of per-scene NDVI with exact count of valid observations per pixel."""
    stack = np.asarray(stack, dtype=np.float32)
    if stack.ndim != 3 or stack.shape[0] < 1:
        raise ValueError('Need at least one aligned 2D observation')
    valid = np.isfinite(stack) & (stack >= -1) & (stack <= 1)
    values = np.where(valid, stack, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', category=RuntimeWarning)
        median = np.nanmedian(values, axis=0).astype(np.float32)
    return median, valid.sum(axis=0, dtype=np.uint16)


def comparison_mask(ndvi0, ndvi1, count0=None, count1=None, min_observations=2):
    a, b = np.asarray(ndvi0), np.asarray(ndvi1)
    if a.shape != b.shape:
        raise ValueError('Raster grids differ')
    valid = np.isfinite(a) & np.isfinite(b) & (a >= -1) & (a <= 1) & (b >= -1) & (b <= 1)
    for count in (count0, count1):
        if count is not None:
            if np.shape(count) != a.shape:
                raise ValueError('Quality grids differ')
            valid &= np.asarray(count) >= min_observations
    return valid


def classify_changes(ndvi0, ndvi1, threshold=.3, valid=None):
    """0 stable class, 1 probable gain, 2 probable loss, 255 no reliable comparison."""
    if not np.isfinite(threshold) or not -1 <= threshold <= 1:
        raise ValueError('NDVI threshold must be between -1 and 1')
    a, b = np.asarray(ndvi0), np.asarray(ndvi1)
    common = comparison_mask(a, b)
    if valid is not None:
        if np.shape(valid) != a.shape:
            raise ValueError('Mask grid differs')
        common &= np.asarray(valid, dtype=bool)
    result = np.full(a.shape, 255, dtype=np.uint8)
    result[common] = 0
    result[common & (a < threshold) & (b >= threshold)] = 1
    result[common & (a >= threshold) & (b < threshold)] = 2
    return result


def compute_statistics(ndvi0, ndvi1, threshold=.3, valid=None, region_mask=None, pixel_area_m2=100):
    if not np.isfinite(pixel_area_m2) or pixel_area_m2 <= 0:
        raise ValueError('Pixel area must be positive')
    a, b = np.asarray(ndvi0), np.asarray(ndvi1)
    common = comparison_mask(a, b)
    region = np.ones(a.shape, dtype=bool) if region_mask is None else np.asarray(region_mask, dtype=bool)
    if region.shape != a.shape:
        raise ValueError('Region grid differs')
    if valid is not None:
        if np.shape(valid) != a.shape:
            raise ValueError('Mask grid differs')
        common &= np.asarray(valid, dtype=bool)
    common &= region
    classified = classify_changes(a, b, threshold, common)
    total, comparable = int(region.sum()), int(common.sum())
    result = {'status': 'ready' if comparable else 'no_data', 'threshold': float(threshold),
              'total_pixels': total, 'comparable_pixels': comparable,
              'comparable_fraction': comparable / total if total else None,
              'comparable_area_ha': comparable * pixel_area_m2 / 10000,
              'pixel_area_m2': pixel_area_m2}
    names = ['vegetation_2020_ha', 'vegetation_2026_ha', 'gain_ha', 'loss_ha', 'net_change_ha',
             'change_percent', 'mean_ndvi_2020', 'mean_ndvi_2026']
    result.update(dict.fromkeys(names))
    if comparable:
        area = pixel_area_m2 / 10000
        old = int((common & (a >= threshold)).sum())
        new = int((common & (b >= threshold)).sum())
        result.update(vegetation_2020_ha=old * area, vegetation_2026_ha=new * area,
                      gain_ha=int((classified == 1).sum()) * area,
                      loss_ha=int((classified == 2).sum()) * area,
                      net_change_ha=(new - old) * area,
                      change_percent=(new - old) / old * 100 if old else None,
                      mean_ndvi_2020=float(a[common].mean(dtype=np.float64)),
                      mean_ndvi_2026=float(b[common].mean(dtype=np.float64)))
    return result
