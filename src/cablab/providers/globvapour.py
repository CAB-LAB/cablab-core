from datetime import datetime, timedelta
import os
import numpy
import netCDF4
from cablab import BaseCubeSourceProvider
from cablab.util import NetCDFDatasetCache, aggregate_images
from skimage.transform import resize

VAR_NAME = 'tcwv_res'


class GlobVapourProvider(BaseCubeSourceProvider):
    def __init__(self, cube_config, dir_path):
        super(GlobVapourProvider, self).__init__(cube_config)
        # todo (nf 20151028) - remove check once we have addressed spatial aggregation/interpolation, see issue #3
        if cube_config.grid_width != 1440 or cube_config.grid_height != 720:
            raise ValueError('illegal cube configuration, '
                             'provider does not yet implement proper spatial aggregation/interpolation')
        self.dir_path = dir_path
        self.source_time_ranges = None
        self.dataset_cache = NetCDFDatasetCache(VAR_NAME)
        self.old_indices = None

    def prepare(self):
        self._init_source_time_ranges()

    def get_variable_descriptors(self):
        return {
            VAR_NAME: {
                'data_type': numpy.float32,
                'fill_value': -999.0,
                'units': 'kg m-2',
                'long_name': 'Total Column Water Vapour',
                'scale_factor': 1.0,
                'add_offset': 0.0,
            }
        }

    def compute_variable_images_from_sources(self, index_to_weight):

        # close all datasets that wont be used anymore
        new_indices = set(index_to_weight.keys())
        if self.old_indices:
            unused_indices = self.old_indices - new_indices
            for i in unused_indices:
                file, time_index = self._get_file_and_time_index(i)
                self.dataset_cache.close_dataset(file)

        self.old_indices = new_indices
        if len(new_indices) == 1:
            i = next(iter(new_indices))
            file, time_index = self._get_file_and_time_index(i)
            dataset = self.dataset_cache.get_dataset(file)
            globvapour = resize(dataset.variables[VAR_NAME][time_index, :, :], (720, 1440), preserve_range=True,
                                order=3)
        else:
            images = [None] * len(new_indices)
            weights = [None] * len(new_indices)
            j = 0
            for i in new_indices:
                file, time_index = self._get_file_and_time_index(i)
                dataset = self.dataset_cache.get_dataset(file)
                variable = resize(dataset.variables[VAR_NAME][time_index, :, :], (720, 1440), preserve_range=True,
                                  order=3)
                images[j] = variable
                weights[j] = index_to_weight[i]
                j += 1
            globvapour = aggregate_images(images, weights=weights)

        return {VAR_NAME: globvapour}

    def _get_file_and_time_index(self, i):
        return self.source_time_ranges[i][2:4]

    def get_source_time_ranges(self):
        return self.source_time_ranges

    def get_spatial_coverage(self):
        return 0, 0, 1440, 720

    def close(self):
        self.dataset_cache.close_all_datasets()

    def _init_source_time_ranges(self):
        source_time_ranges = []
        dir_names = os.listdir(self.dir_path)

        for dir_name in dir_names:
            file_names = os.listdir(os.path.join(self.dir_path,dir_name))
            for file_name in file_names:
                file = os.path.join(self.dir_path,dir_name,file_name)
                dataset = self.dataset_cache.get_dataset(file)
                time = dataset.variables['time']
                dates1 = netCDF4.num2date(time[:], 'days since 1970-01-01 00:00:00', calendar='gregorian')
                self.dataset_cache.close_dataset(file)
                t1 = datetime(dates1.year, dates1.month, dates1.day)
                # use this one for weekly data
                # t2 = t1 +  timedelta(days=7)
                t2 = self._last_day_of_month(t1) + timedelta(days=1)
                source_time_ranges.append((t1, t2, file, 0))
        self.source_time_ranges = sorted(source_time_ranges, key=lambda item: item[0])

    @staticmethod
    def _last_day_of_month(any_day):
        next_month = any_day.replace(day=28) + timedelta(days=4)
        return next_month - timedelta(days=next_month.day)