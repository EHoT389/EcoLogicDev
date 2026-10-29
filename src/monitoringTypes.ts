export type MonitoringMode='2020'|'2026'|'changes'|'swipe';
export type MonitoringScene={id:string;date?:string;datetime?:string;source?:string;cloud_cover?:number;cloud_percent?:number;assets?:Record<string,unknown>};
export type MonitoringPeriod={start?:string;end?:string;scene_count?:number;scenes?:MonitoringScene[]};
export type MonitoringMetadata={
 status:string;reason?:string;version?:string;dataset_id?:string;bbox_wgs84?:[number,number,number,number];scope?:string;resolution_m?:number;
 periods?:Record<string,MonitoringPeriod>;methodology?:string|Record<string,unknown>;warnings?:string[];
 source?:{catalog?:string;attribution?:string;scenes?:MonitoringScene[]};
};
export type MonitoringStatistics={
 vegetation_2020_ha:number|null;vegetation_2026_ha:number|null;gain_ha:number|null;loss_ha:number|null;net_change_ha:number|null;change_percent:number|null;
 mean_ndvi_2020:number|null;mean_ndvi_2026:number|null;mean_ndvi_difference:number|null;comparable_fraction:number|null;total_pixels:number;comparable_pixels:number;
 scope_area_ha?:number;requested_area_ha?:number;aoi_coverage_fraction?:number;
};
export type MonitoringResult={
 status:string;reason?:string;zone_id?:string|null;territory?:{ru:string;kk:string};period_start:number;period_end:number;threshold:number;
 statistics:MonitoringStatistics;warnings?:string[];source?:MonitoringMetadata['source'];
};
