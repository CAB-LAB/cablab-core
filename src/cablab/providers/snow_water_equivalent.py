import os
from datetime import datetime, timedelta

import netCDF4
import numpy

from cablab import NetCDFCubeSourceProvider


class SnowWaterEquivalentProvider(NetCDFCubeSourceProvider):
    def __init__(self, cube_config, name, dir_path):
        super(SnowWaterEquivalentProvider, self).__init__(cube_config, name, dir_path)
        self.old_indices = None

    @property
    def variable_descriptors(self):
        return {
            'snow_water_equivalent': {
                'source_name': 'SWE',
                'data_type': numpy.float32,
                'fill_value': -9999.0,
                'units': 'mm',
                'long_name': 'daily snow water equivalent',
                'scale_factor': 1.0,
                'add_offset': 0.0,
                'certain_values': "-2 == mountains, -1 == water bodies, 0 == either SWE, "
                                  "or missing data in the southern hemisphere",
            }
        }

    def close(self):
        self.dataset_cache.close_all_datasets()

    def compute_source_time_ranges(self):
        source_time_ranges = []
        file_names = os.listdir(self.dir_path)
        for file_name in file_names:
            file = os.path.join(self.dir_path, file_name)
            dataset = self.dataset_cache.get_dataset(file)
            time_bnds = dataset.variables['time']
            time = netCDF4.num2date(time_bnds[:], 'days since 1582-10-15 00:00', calendar='gregorian')
            self.dataset_cache.close_dataset(file)
            for i in range(len(time)):
                t1 = datetime(time[i].year, time[i].month, time[i].day)
                t2 = t1 + timedelta(days=1)
                source_time_ranges.append((t1, t2, file, i))
        return sorted(source_time_ranges, key=lambda item: item[0])
