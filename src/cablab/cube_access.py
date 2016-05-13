import math
import os
from collections import OrderedDict
from datetime import timedelta

import xarray as xr


class _Variable:
    def __init__(self, index, name, dir_path):
        self.index = index
        self.name = name
        self.dir_path = dir_path
        self.dataset = None


class CubeDataAccess:
    """
    Represents the cube's data.

    :param cube: A **Cube** object.
    """

    def __init__(self, cube):

        self._cube = cube

        self._variable_dict = OrderedDict()
        self._variable_list = []

        data_dir = os.path.join(cube.base_dir, 'data')
        data_dir_entries = os.listdir(data_dir)
        var_index = 0
        for data_dir_entry in data_dir_entries:
            var_dir = os.path.join(data_dir, data_dir_entry)
            if os.path.isdir(var_dir):
                var_name = data_dir_entry
                variable = _Variable(var_index, var_name, var_dir)
                self._variable_dict[var_name] = variable
                self._variable_list.append(variable)
                var_index += 1

    @property
    def variable_names(self) -> tuple:
        """
        Return a sequence of variable names.
        """
        return [variable.name for variable in self._variable_list]

    def variables(self, key=None):
        """
        Get one or more cube variables as ``xarray.DataArray`` instances. Same as, e.g. ``cube.data['ozone']``.

        :param key: The variable selector, which can be a name, or index, or a sequence of names and indices.
                Valid names (type ``str``) are the ones returned by the ``variable_names`` list while valid
                indices (type ``int``) point into this list.
                If a sequence is provided, a sequence will be returned.
                Passing ``None`` is equivalent to passing the ``variable_names`` list.
        :return: a ``xarray.DataArray`` instance or a sequence of such representing the variable(s) with the
                dimensions (time, latitude, longitude).
        """

        if isinstance(key, int):
            key = self._variable_list[key]
            dataset = self._get_or_open_dataset(key)
            return dataset.variables[key.name]
        elif isinstance(key, str):
            key = self._variable_dict[key]
            dataset = self._get_or_open_dataset(key)
            return dataset.variables[key.name]
        elif not isinstance(key, tuple):
            indices = self._get_var_indices(key)
            data_arrays = []
            for i in indices:
                key = self._variable_list[i]
                dataset = self._get_or_open_dataset(key)
                data_arrays.append(dataset.variables[key.name])
            return data_arrays
        else:
            raise IndexError('key cannot be a tuple')

    def dataset(self, key=None):
        """
        Get one or more cube variables as ``xarray.Dataset`` instances.

        :param key: The variable selector, which can be a name, or index, or a sequence of names and indices.
                Valid names (type ``str``) are the ones returned by the ``variable_names`` list while valid
                indices (type ``int``) point into this list.
                If a sequence is provided, a sequence will be returned.
                Passing ``None`` is equivalent to passing the ``variable_names`` list.
        :return: a ``xarray.Dataset`` instance with the dimensions (time, latitude, longitude).
        """

        if isinstance(key, int):
            key = self._variable_list[key]
            return self._get_or_open_dataset(key)
        elif isinstance(key, str):
            key = self._variable_dict[key]
            return self._get_or_open_dataset(key)
        elif not isinstance(key, tuple):
            indices = self._get_var_indices(key)
            data_arrays = {}
            for i in indices:
                key = self._variable_list[i]
                dataset = self._get_or_open_dataset(key)
                data_arrays[key.name] = dataset.variables[key.name]
            return xr.Dataset(data_arrays)
        else:
            raise IndexError('key cannot be a tuple')

    def __getitem__(self, key):
        """
        Same as ``variable(key=key)``.
        """
        return self.variables(key=key)

    def __iter__(self):
        return iter(self._variable_list)

    def __len__(self):
        return len(self._variable_list)

    def get(self, variable=None, time=None, latitude=None, longitude=None):
        """
        Get the cube's data.

        :param variable: an variable index or name or an iterable returning multiple of these (var1, var2, ...)
        :param time: a single datetime.datetime object or a 2-element iterable (time_start, time_end)
        :param latitude: a single latitude value or a 2-element iterable (latitude_start, latitude_end)
        :param longitude: a single longitude value or a 2-element iterable (longitude_start, longitude_end)
        :return: a dictionary mapping variable names --> data arrays of dimension (time, latitude, longitude)
        """

        var_indexes = self._get_var_indices(variable)
        time_1, time_2 = self._get_time_range(time)
        lat_1, lat_2 = self._get_lat_range(latitude)
        lon_1, lon_2 = self._get_lon_range(longitude)

        config = self._cube.config
        time_index_1 = int(math.floor(((time_1 - config.ref_time) / timedelta(days=config.temporal_res))))
        time_index_2 = int(math.floor(((time_2 - config.ref_time) / timedelta(days=config.temporal_res))))
        grid_y1 = int(round((90.0 - lat_2) / config.spatial_res)) - config.grid_y0
        grid_y2 = int(round((90.0 - lat_1) / config.spatial_res)) - config.grid_y0
        grid_x1 = int(round((180.0 + lon_1) / config.spatial_res)) - config.grid_x0
        grid_x2 = int(round((180.0 + lon_2) / config.spatial_res)) - config.grid_x0

        if grid_y2 > grid_y1 and 90.0 - (grid_y2 + config.grid_y0) * config.spatial_res == lat_1:
            grid_y2 -= 1
        if grid_x2 > grid_x1 and -180.0 + (grid_x2 + config.grid_x0) * config.spatial_res == lon_2:
            grid_x2 -= 1

        global_grid_width = int(round(360.0 / config.spatial_res))
        dateline_intersection = grid_x2 >= global_grid_width

        if dateline_intersection:
            grid_x11 = grid_x1
            grid_x12 = global_grid_width - 1
            grid_x21 = 0
            grid_x22 = grid_x2
            # todo (nf 20151102) - Handle data requests intersecting the dateline, see issue #15
            print('dateline intersection! grid_x: %d-%d, %d-%d' % (grid_x11, grid_x12, grid_x21, grid_x22))
            raise ValueError('illegal longitude: %s: dateline intersection not yet implemented' % longitude)

        # todo (nf 20151102) - Fill in NaN, where a variable does not provide any data, see issue #17
        result = []
        # shape = time_index_2 - time_index_1 + 1, \
        #         grid_y2 - grid_y1 + 1, \
        #         grid_x2 - grid_x1 + 1
        for var_index in var_indexes:
            variable = self.variables(var_index)
            # result += [numpy.full(shape, numpy.NaN, dtype=numpy.float32)]
            # print('variable.shape =', variable.shape)
            array = variable[slice(time_index_1, time_index_2 + 1) if (time_index_1 < time_index_2) else time_index_1,
                             slice(grid_y1, grid_y2 + 1) if (grid_y1 < grid_y2) else grid_y1,
                             slice(grid_x1, grid_x2 + 1) if (grid_x1 < grid_x2) else grid_x1]
            result += [array]
        return result

    def close(self):
        """
        Closes this **CubeData** by closing all open datasets.
        """
        self._close_datasets()

    def _get_lon_range(self, longitude):
        if longitude is None:
            return -180, 180
        try:
            # Try using longitude as longitude pair
            lon_1, lon_2 = longitude
        except TypeError:
            # Longitude scalar
            lon_1 = longitude
            lon_2 = longitude
        # Adjust longitude to -180..+180
        if lon_1 < -180:
            lon_1 %= 180
        if lon_1 > 180:
            lon_1 %= -180
        if lon_2 < -180:
            lon_2 %= 180
        if lon_2 > 180:
            lon_2 %= -180
        # If lon_1 > lon_2 --> dateline intersection, add 360 so that lon_1 < lon_2
        if lon_1 > lon_2:
            lon_2 += 360
        return lon_1, lon_2

    def _get_lat_range(self, latitude):
        if latitude is None:
            return -90, 90
        try:
            # Try using latitude as latitude pair
            lat_1, lat_2 = latitude
        except TypeError:
            # Latitude scalar
            lat_1 = latitude
            lat_2 = latitude
        if lat_1 < -90 or lat_1 > 90 or lat_2 < -90 or lat_2 > 90 or lat_1 > lat_2:
            raise ValueError('invalid latitude argument: %s' % latitude)
        return lat_1, lat_2

    def _get_time_range(self, time):
        if time is None:
            return self._cube.config.start_time, self._cube.config.end_time
        try:
            # Try using time as time pair
            time_1, time_2 = time
        except TypeError:
            # Time scalar
            time_1 = time
            time_2 = time
        if time_1 > time_2:
            raise ValueError('invalid time argument: %s' % time)
        return time_1, time_2

    def _get_var_indices(self, variable):
        if variable is None:
            return range(len(self._variable_list))
        try:
            # Try using variable as string name
            var_index = self._variable_dict[variable].index
            return [var_index]
        except (KeyError, TypeError):
            try:
                # Try using variable as integer index
                _ = self._variable_list[variable]
                return [variable]
            except (KeyError, TypeError):
                # Try using variable as iterable of name and/or indexes
                var_indexes = []
                for v in variable:
                    try:
                        # Try using v as string name
                        var_index = self._variable_dict[v].index
                        var_indexes += [var_index]
                    except (KeyError, TypeError):
                        try:
                            # Try using v as integer index
                            _ = self._variable_list[v]
                            var_index = v
                            var_indexes += [var_index]
                        except (KeyError, TypeError):
                            raise ValueError('illegal variable argument: %s' % variable)
                return var_indexes

    def _get_or_open_dataset(self, variable):
        if not variable.dataset:
            self._open_dataset(variable)
        return variable.dataset

    def _open_dataset(self, variable):
        file_pattern = os.path.join(variable.dir_path, '*.nc')
        variable.dataset = xr.open_mfdataset(file_pattern,
                                             concat_dim='time',
                                             engine='h5netcdf')

    def _close_datasets(self):
        for variable in self._variable_list:
            if variable.dataset:
                variable.dataset.close()
                variable.dataset = None
