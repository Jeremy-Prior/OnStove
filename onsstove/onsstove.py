import os
from csv import DictReader

import psycopg2
import pandas as pd
import geopandas as gpd
import numpy as np
from typing import Dict, Any
from shapely.geometry import shape
import scipy.spatial

from onsstove.technology import Technology, LPG, Biomass, Electricity
from .raster import *
from .layer import VectorLayer, RasterLayer


class DataProcessor:
    """
    Class containing the methods to perform a Multi Criteria Analysis
    of clean cooking access potential. It calculates a Clean Cooking Demand
    Index, a Clean Cooking Supply Index and a Clean Cooking Potential Index
    """
    conn = None
    base_layer = None

    def __init__(self, project_crs=None, cell_size=None, output_directory='output'):
        """
        Initializes the class and sets an empty layers dictionaries.
        """
        self.layers = {}
        self.project_crs = project_crs
        self.cell_size = cell_size
        self.output_directory = output_directory
        self.mask_layer = None

    def get_layers(self, layers):
        if layers == 'all':
            _layers = self.layers
        else:
            _layers = {}
            for category, names in layers.items():
                _layers[category] = {}
                for name in names:
                    _layers[category][name] = self.layers[category][name]
        return _layers

    def set_postgres(self, db, POSTGRES_USER, POSTGRES_KEY):
        """
        Sets a conecion to a PostgreSQL database

        Parameters
        ----------
        arg1 :
        """
        self.conn = psycopg2.connect(database=db,
                                     user=POSTGRES_USER,
                                     password=POSTGRES_KEY)

    def add_layer(self, category, name, layer_path, layer_type, query=None,
                  postgres=False, base_layer=False, resample='nearest',
                  normalization=None, inverse=False, distance=None,
                  distance_limit=float('inf')):
        """
        Adds a new layer (type VectorLayer or RasterLayer) to the MCA class

        Parameters
        ----------
        arg1 :
        """
        output_path = os.path.join(self.output_directory, category, name)
        os.makedirs(output_path, exist_ok=True)

        if layer_type == 'vector':
            if postgres:
                layer = VectorLayer(category, name, layer_path, conn=self.conn,
                                    normalization=normalization,
                                    distance=distance,
                                    distance_limit=distance_limit,
                                    inverse=inverse, query=query)
            else:
                layer = VectorLayer(category, name, layer_path,
                                    normalization=normalization,
                                    distance=distance,
                                    distance_limit=distance_limit,
                                    inverse=inverse, query=query)

        elif layer_type == 'raster':
            layer = RasterLayer(category, name, layer_path,
                                normalization=normalization, inverse=inverse,
                                distance=distance, resample=resample)

            if base_layer:
                if not self.cell_size:
                    self.cell_size = (layer.meta['transform'][0],
                                      abs(layer.meta['transform'][4]))
                if not self.project_crs:
                    self.project_crs = layer.meta['crs']

                cell_size_diff = abs(self.cell_size[0] - layer.meta['transform'][0]) / \
                                 layer.meta['transform'][0]

                if (layer.meta['crs'] != self.project_crs) or (cell_size_diff > 0.01):
                    layer.reproject(self.project_crs,
                                    output_path=output_path,
                                    cell_width=self.cell_size[0],
                                    cell_height=self.cell_size[1])

                self.base_layer = layer

        if category in self.layers.keys():
            self.layers[category][name] = layer
        else:
            self.layers[category] = {name: layer}

    def add_mask_layer(self, category, name, layer_path, postgres=False, query=None):
        """
        Adds a vector layer to self.mask_layer, which will be used to mask all
        other layers into is boundaries
        """
        if postgres:
            self.mask_layer = VectorLayer(category, name, layer_path, self.conn, query)
        else:
            self.mask_layer = VectorLayer(category, name, layer_path, query=query)

        if self.mask_layer.layer.crs != self.project_crs:
            output_path = os.path.join(self.output_directory, category, name)
            self.mask_layer.reproject(self.project_crs, output_path)

    def mask_layers(self, datasets='all'):
        """
        Uses the previously added mask layer in self.mask_layer to mask all
        other layers to its boundaries
        """
        if not isinstance(self.mask_layer, VectorLayer):
            raise Exception('The `mask_layer` attribute is empty, please first ' + \
                            'add a mask layer using the `.add_mask_layer` method.')
        datasets = self.get_layers(datasets)
        for category, layers in datasets.items():
            for name, layer in layers.items():
                output_path = os.path.join(self.output_directory,
                                           category, name)
                os.makedirs(output_path, exist_ok=True)
                if name != self.base_layer.name:
                    all_touched = True
                else:
                    all_touched = False
                layer.mask(self.mask_layer.layer, output_path, all_touched=all_touched)
                if isinstance(layer.friction, RasterLayer):
                    layer.friction.mask(self.mask_layer.layer, output_path)

    def align_layers(self, datasets='all'):
        datasets = self.get_layers(datasets)
        for category, layers in datasets.items():
            for name, layer in layers.items():
                output_path = os.path.join(self.output_directory,
                                           category, name)
                os.makedirs(output_path, exist_ok=True)
                if isinstance(layer, VectorLayer):
                    if isinstance(layer.friction, RasterLayer):
                        layer.friction.align(self.base_layer.path, output_path)
                else:
                    if name != self.base_layer.name:
                        layer.align(self.base_layer.path, output_path)
                    if isinstance(layer.friction, RasterLayer):
                        layer.friction.align(self.base_layer.path, output_path)

    def reproject_layers(self, datasets='all'):
        """
        Goes through all layer and call their `.reproject` method with the
        `project_crs` as argument
        """
        datasets = self.get_layers(datasets)
        for category, layers in datasets.items():
            for name, layer in layers.items():
                output_path = os.path.join(self.output_directory,
                                           category, name)
                os.makedirs(output_path, exist_ok=True)
                layer.reproject(self.project_crs, output_path)
                if isinstance(layer.friction, RasterLayer):
                    layer.friction.reproject(self.project_crs, output_path)

    def get_distance_rasters(self, datasets='all'):
        """
        Goes through all layer and call their `.distance_raster` method
        """
        datasets = self.get_layers(datasets)
        for category, layers in datasets.items():
            for name, layer in layers.items():
                output_path = os.path.join(self.output_directory,
                                           category, name)
                os.makedirs(output_path, exist_ok=True)
                layer.get_distance_raster(self.base_layer.path,
                                          output_path, self.mask_layer.layer)
                if isinstance(layer.friction, RasterLayer):
                    layer.friction.get_distance_raster(self.base_layer.path,
                                                       output_path, self.mask_layer.layer)

    def normalize_rasters(self, datasets='all'):
        """
        Goes through all layer and call their `.normalize` method
        """
        datasets = self.get_layers(datasets)
        for category, layers in datasets.items():
            for name, layer in layers.items():
                output_path = os.path.join(self.output_directory,
                                           category, name)
                layer.distance_raster.normalize(output_path, self.mask_layer.layer)

    @staticmethod
    def index(layers):
        weights = []
        rasters = []
        for name, layer in layers.items():
            rasters.append(layer.weight * layer.distance_raster.normalized.layer)
            weights.append(layer.weight)

        return sum(rasters) / sum(weights)

    def get_demand_index(self, datasets='all'):
        datasets = self.get_layers(datasets)['demand']
        layer = RasterLayer('Indexes', 'Demand_index', normalization='MinMax')
        layer.layer = self.index(datasets)
        layer.meta = self.base_layer.meta
        output_path = os.path.join(self.output_directory,
                                   'Indexes', 'Demand Index')
        os.makedirs(output_path, exist_ok=True)
        layer.normalize(output_path, self.mask_layer.layer)
        layer.normalized.name = 'Demand Index'
        self.demand_index = layer.normalized

    def get_supply_index(self, datasets='all'):
        datasets = self.get_layers(datasets)['supply']
        layer = RasterLayer('Indexes', 'Supply index', normalization='MinMax')
        layer.layer = self.index(datasets)
        layer.meta = self.base_layer.meta
        output_path = os.path.join(self.output_directory,
                                   'Indexes', 'Supply Index')
        os.makedirs(output_path, exist_ok=True)
        layer.normalize(output_path, self.mask_layer.layer)
        layer.normalized.name = 'Supply Index'
        self.supply_index = layer.normalized

    def get_clean_cooking_index(self, demand_weight=1, supply_weight=1):
        layer = RasterLayer('Indexes', 'Clean Cooking Potential Index', normalization='MinMax')
        layer.layer = (demand_weight * self.demand_index.layer + supply_weight * self.supply_index.layer) / \
                      (demand_weight + supply_weight)
        layer.meta = self.base_layer.meta
        output_path = os.path.join(self.output_directory,
                                   'Indexes', 'Clean Cooking Potential Index')
        os.makedirs(output_path, exist_ok=True)
        layer.normalize(output_path, self.mask_layer.layer)
        layer.normalized.name = 'Clean Cooking Potential Index'
        self.clean_cooking_index = layer.normalized

    def save_datasets(self, datasets='all'):
        """
        Saves all layers that have not been previously saved
        """
        datasets = self.get_layers(datasets)
        for category, layers in datasets.items():
            for name, layer in layers.items():
                output_path = os.path.join(self.output_directory,
                                           category, name)
                layer.save(output_path)


class OnSSTOVE(DataProcessor):
    """
    Class containing the methods to perform a geospatial max-benefit analysis
    on clean cooking access
    """
    conn = None
    base_layer = None

    population = 'path_to_file'

    def __init__(self, project_crs=None, cell_size=None, output_directory='output'):
        """
        Initializes the class and sets an empty layers dictionaries.
        """
        super().__init__(project_crs, cell_size, output_directory)
        self.specs = None
        self.techs = None
        self.base_fuel = None
        self.i = {}

    def get_layers(self, layers):
        if layers == 'all':
            layers = self.layers
        else:
            layers = {category: {name: self.layers[category][name]} for category, names in layers.items() for name in
                      names}
        return layers

    def set_postgres(self, db, POSTGRES_USER, POSTGRES_KEY):
        """
        Sets a conecion to a PostgreSQL database

        Parameters
        ----------
        arg1 : 
        """
        self.conn = psycopg2.connect(database=db,
                                     user=POSTGRES_USER,
                                     password=POSTGRES_KEY)

    def read_scenario_data(self, path_to_config: str, delimiter=','):
        """Reads the scenario data into a dictionary
        """
        config = {}
        with open(path_to_config, 'r') as csvfile:
            reader = DictReader(csvfile, delimiter=delimiter)
            config_file = list(reader)
            for row in config_file:
                if row['Value']:
                    if row['data_type'] == 'int':
                        config[row['Param']] = int(row['Value'])
                    elif row['data_type'] == 'float':
                        config[row['Param']] = float(row['Value'])
                    elif row['data_type'] == 'string':
                        config[row['Param']] = str(row['Value'])
                    else:
                        raise ValueError("Config file data type not recognised.")
        self.specs = config

    def read_tech_data(self, path_to_config: str, delimiter=','):
        """
        Reads the technology data from a csv file into a dictionary
        """
        techs = {}
        with open(path_to_config, 'r') as csvfile:
            reader = DictReader(csvfile, delimiter=delimiter)
            config_file = list(reader)
            for row in config_file:
                if row['Value']:
                    if row['Fuel'] not in techs:
                        if row['Fuel'] == 'LPG':
                            techs[row['Fuel']] = LPG()
                        elif 'biomass' in row['Fuel'].lower():
                            techs[row['Fuel']] = Biomass()
                        elif 'electricity' in row['Fuel'].lower():
                            techs[row['Fuel']] = Electricity()
                        else:
                            techs[row['Fuel']] = Technology()
                    if row['data_type'] == 'int':
                        techs[row['Fuel']][row['Param']] = int(row['Value'])
                    elif row['data_type'] == 'float':
                        techs[row['Fuel']][row['Param']] = float(row['Value'])
                    elif row['data_type'] == 'string':
                        techs[row['Fuel']][row['Param']] = str(row['Value'])
                    elif row['data_type'] == 'bool':
                        techs[row['Fuel']][row['Param']] = bool(row['Value'])
                    else:
                        raise ValueError("Config file data type not recognised.")
        for name, tech in techs.items():
            if tech.is_base:
                self.base_fuel = tech

        self.techs = techs


    def normalized(self, column, inverse = False):

        if inverse:
            normalized = (self.gdf[column].max() - self.gdf[column])/(self.gdf[column].max() - self.gdf[column].min())
        else:
            normalized = (self.gdf[column] - self.gdf[column].min())/(self.gdf[column].max() - self.gdf[column].min())

        return normalized

    def normalize_for_electricity(self):

        if "Transformers_dist" in self.gdf.columns:
            self.gdf["Elec_dist"] = self.gdf["Transformers_dist"]
        elif "MV_lines_dist" in self.gdf.columns:
            self.gdf["Elec_dist"] = self.gdf["MV_lines_dist"]
        else:
            self.gdf["Elec_dist"] = self.gdf["HV_lines_dist"]

        elec_dist = self.normalized("Elec_dist", inverse = True)
        ntl = self.normalized("Night_lights")
        pop = self.normalized("Calibrated_pop")


        self.combined_weight = (elec_dist * self.specs["infra_weight"] + pop * self.specs["Min_Elec_Pop"] +
                 ntl * self.specs["Min_Night_Lights"]) / (self.specs["infra_weight"] + self.specs["Min_Elec_Pop"] +
                                                          self.specs["Min_Night_Lights"])

    def current_elec(self):
        self.normalize_for_electricity()
        elec_rate = self.specs["Elec_rate"]

        self.gdf["Current_elec"] = 0

        i = 1
        elec_pop = 0
        total_pop = self.gdf["Calibrated_pop"].sum()

        while elec_pop <= total_pop * elec_rate:
            bool = (self.combined_weight >= i)
            elec_pop = self.gdf.loc[bool, "Calibrated_pop"].sum()

            self.gdf.loc[bool, "Current_elec"] = 1
            i = i - 0.0001

        self.i = i

    def final_elec(self):

        elec_rate = self.specs["Elec_rate"]

        self.gdf["Elec_pop_calib"] = self.gdf["Calibrated_pop"]

        i = self.i + 0.0001
        total_pop = self.gdf["Calibrated_pop"].sum()
        elec_pop = self.gdf.loc[self.gdf["Current_elec"] == 1, "Calibrated_pop"].sum()
        diff = elec_pop - (total_pop * elec_rate)
        factor = diff/self.gdf["Current_elec"].count()


        while elec_pop > total_pop * elec_rate:

            new_bool = (self.i <= self.combined_weight) & (self.combined_weight <= i)

            self.gdf.loc[new_bool, "Elec_pop_calib"] -= factor
            self.gdf.loc[self.gdf["Elec_pop_calib"] < 0, "Elec_pop_calib"] = 0
            self.gdf.loc[self.gdf["Elec_pop_calib"] == 0, "Current_elec"] = 0
            bool = self.gdf["Current_elec"] == 1

            elec_pop = self.gdf.loc[bool, "Elec_pop_calib"].sum()

            new_bool = bool & new_bool
            if new_bool.sum() == 0:
                i = i + 0.0001

        self.gdf.loc[self.gdf["Current_elec"] == 0, "Elec_pop_calib"] = 0


    def calibrate_current_pop(self):

        total_gis_pop = self.gdf["Pop"].sum()
        calibration_factor = self.specs["Population_start_year"] / total_gis_pop

        self.gdf["Calibrated_pop"] = self.gdf["Pop"] * calibration_factor

    def distance_to_electricity(self, hv_lines=None, mv_lines=None, transformers=None):
        """
        Cals the get_distance_raster method for the HV. MV and Transformers
        layers (if available) and converts the output to a column in the
        main gdf
        """
        if (not hv_lines) and (not mv_lines) and (not transformers):
            raise ValueError("You MUST provide at least one of the following datasets: hv_lines, mv_lines or "
                             "transformers.")

        for layer in [hv_lines, mv_lines, transformers]:
            if layer:
                output_path = os.path.join(self.output_directory,
                                           layer.category,
                                           layer.name)
                layer.get_distance_raster(self.base_layer.path,
                                          output_path,
                                          self.mask_layer.layer)
                layer.distance_raster.layer /= 1000  # to convert from meters to km
                self.raster_to_dataframe(layer.distance_raster.layer,
                                         name=layer.distance_raster.name,
                                         method='read')

    def population_to_dataframe(self, layer=None):
        """
        Takes a population `RasterLayer` as input and extracts the populated points to a GeoDataFrame that is
        saved in `OnSSTOVE.gdf`.
        """
        if not layer:
            if self.base_layer:
                layer = self.base_layer
            else:
                raise ValueError("No population layer was provided as input to the method or in the model base_layer")

        self.rows, self.cols = np.where(~np.isnan(layer.layer))
        x, y = rasterio.transform.xy(layer.meta['transform'],
                                     self.rows, self.cols,
                                     offset='center')

        self.gdf = gpd.GeoDataFrame({'geometry': gpd.points_from_xy(x, y),
                                     'Pop': layer.layer[self.rows, self.cols]})
        self.gdf.crs = self.project_crs

    def raster_to_dataframe(self, layer, name=None, method='sample'):
        """
        Takes a RasterLayer and a method (sample or read), gets the values from the raster layer using the population points previously extracted and saves the values in a new column of OnSSTOVE.gdf
        """
        if method == 'sample':
            with rasterio.open(layer) as src:
                if src.meta['crs'] != self.gdf.crs:
                    self.gdf[name] = sample_raster(layer, self.gdf.to_crs(src.meta['crs']))
        elif method == 'read':
            self.gdf[name] = layer[self.rows, self.cols]

    def calibrate_urban_current_and_future_GHS(self, GHS_path):
        self.raster_to_dataframe(GHS_path, name="IsUrban", method='sample')

        if self.specs["End_year"] > self.specs["Start_year"]:
            population_current = self.specs["Population_end_year"]
            urban_current = self.specs["Urban_start"] * population_current
            rural_current = population_current - urban_current

            population_future = self.specs["Population_end_year"]
            urban_future = self.specs["Urban_end"] * population_future
            rural_future = population_future - urban_future

            rural_growth = (rural_future - rural_current)/(self.specs["End_Year"] - self.specs["Start_Year"])
            urban_growth = (urban_future - urban_current) / (self.specs["End_Year"] - self.specs["Start_Year"])

            self.gdf.loc[self.gdf['IsUrban'] > 20, 'Pop_future'] = self.gdf["Calibrated_pop"] * urban_growth
            self.gdf.loc[self.gdf['IsUrban'] < 20, 'Pop_future'] = self.gdf["Calibrated_pop"] * rural_growth

        self.number_of_households()

    def calibrate_urban_manual(self):

        urban_modelled = 2
        factor = 1
        pop_tot = self.specs["Population_start_year"]
        urban_current = self.specs["Urban_start"]

        i = 0
        while abs(urban_modelled - urban_current) > 0.01:

            self.gdf["IsUrban"] = 0
            self.gdf.loc[(self.gdf["Calibrated_pop"] > 5000 * factor) & (
                    self.gdf["Calibrated_pop"] / (self.cell_size[0] ** 2 / 1000000) > 350 * factor), "IsUrban"] = 1
            self.gdf.loc[(self.gdf["Calibrated_pop"] > 50000 * factor) & (
                    self.gdf["Calibrated_pop"] / (self.cell_size[0] ** 2 / 1000000) > 1500 * factor), "IsUrban"] = 2

            pop_urb = self.gdf.loc[self.gdf["IsUrban"] > 1, "Calibrated_pop"].sum()

            urban_modelled = pop_urb / pop_tot

            if urban_modelled > urban_current:
                factor *= 1.1
            else:
                factor *= 0.9
            i = i + 1
            if i > 500:
                break


    def number_of_households(self):

        self.gdf.loc[self.gdf["IsUrban"] < 20, 'Households'] = self.gdf.loc[
                                                                    self.gdf["IsUrban"] < 20, 'Calibrated_pop'] / \
                                                                self.specs["Rural_HHsize"]
        self.gdf.loc[self.gdf["IsUrban"] > 20, 'Households'] = self.gdf.loc[self.gdf["IsUrban"] > 20, 'Calibrated_pop'] / \
                                                               self.specs["Urban_HHsize"]

    def get_value_of_time(self):
        """
        Calculates teh value of time based on the minimum wage ($/h) and a
        GIS raster map as wealth index, poverty or GDP
        ----
        0.5 is the upper limit for minimum wage and 0.2 the lower limit
        """
        min_value = np.nanmin(self.gdf['relative_wealth'])
        max_value = np.nanmax(self.gdf['relative_wealth'])
        norm_layer = (self.gdf['relative_wealth'] - min_value) / (max_value - min_value) * (0.5 - 0.2) + 0.2
        self.gdf['value_of_time'] = norm_layer * self.specs['Minimum_wage'] / 30 / 24  # convert $/months to $/h


    def maximum_net_benefit(self):
        net_benefit_cols = [col for col in self.gdf if 'net_benefit_' in col]
        self.gdf["max_benefit_tech"] = self.gdf[net_benefit_cols].idxmax(axis=1)

        self.gdf['max_benefit_tech'] = self.gdf['max_benefit_tech'].str.replace("net_benefit_", "")
        self.gdf["maximum_net_benefit"] = self.gdf[net_benefit_cols].max(axis=1)  # * self.gdf['Households']

        current_elect = (self.gdf['Current_elec'] == 1) & (self.gdf['Elec_pop_calib'] < self.gdf['Calibrated_pop']) & \
                        (self.gdf["max_benefit_tech"] == 'Electricity')
        if current_elect.sum() > 0:
            elect_fraction = self.gdf.loc[current_elect, "Elec_pop_calib"] / self.gdf.loc[
                current_elect, "Calibrated_pop"]
            self.gdf.loc[current_elect, "maximum_net_benefit"] *= elect_fraction

            second_benefit_cols = [col for col in self.gdf if 'net_benefit_' in col]
            second_benefit_cols.remove('net_benefit_Electricity')
            second_best = self.gdf.loc[current_elect, second_benefit_cols].idxmax(axis=1).str.replace("net_benefit_",
                                                                                                      "")

            second_best_value = self.gdf.loc[current_elect, second_benefit_cols].max(axis=1) * (1 - elect_fraction)
            second_tech_net_benefit = second_best_value  # * self.gdf.loc[current_elect, 'Households']
            dff = self.gdf.loc[current_elect].copy()
            dff['max_benefit_tech'] = second_best
            dff['maximum_net_benefit'] = second_tech_net_benefit
            dff['Calibrated_pop'] *= (1 - elect_fraction)
            dff['Elec_pop_calib'] *= (1 - elect_fraction)
            dff['Households'] *= (1 - elect_fraction)

            self.gdf.loc[current_elect, 'Calibrated_pop'] *= elect_fraction
            self.gdf.loc[current_elect, 'Elec_pop_calib'] *= elect_fraction
            self.gdf.loc[current_elect, 'Households'] *= elect_fraction
            self.gdf = self.gdf.append(dff)

        # current_biogas = (self.gdf["needed_energy"] * self.gdf["Households"] >= self.gdf["available_biogas_energy"]) & \
        #                  (self.gdf["max_benefit_tech"] == 'Biogas')
        # if current_biogas.sum() > 0:
        #     biogas_fraction = self.gdf.loc[current_biogas, "available_biogas_energy"] / \
        #                       self.gdf.loc[current_biogas, "needed_energy"]
        #     self.gdf.loc[current_biogas, "maximum_net_benefit"] *= biogas_fraction
        #
        #     second_benefit_cols = [col for col in self.gdf if 'net_benefit_' in col]
        #     second_benefit_cols.remove('net_benefit_Biogas')
        #     second_best_biogas = self.gdf.loc[current_biogas, second_benefit_cols].idxmax(axis=1).str.replace("net_benefit_", "")
        #
        #     second_best_value = self.gdf.loc[current_biogas, second_benefit_cols].max(axis=1) * (1 - biogas_fraction)
        #     second_tech_net_benefit = second_best_value #* self.gdf.loc[current_elect, 'Households']
        #     dff = self.gdf.loc[current_biogas].copy()
        #     dff['max_benefit_tech'] = second_best_biogas
        #     dff['maximum_net_benefit'] = second_tech_net_benefit
        #     dff['Calibrated_pop'] *= (1 - biogas_fraction)
        #     dff['Households'] *= (1 - biogas_fraction)
        #
        #     self.gdf.loc[current_biogas, 'Calibrated_pop'] *= biogas_fraction
        #     self.gdf.loc[current_biogas, 'Households'] *= biogas_fraction
        #     self.gdf = self.gdf.append(dff)

    def add_admin_names(self, admin, column_name):

        if isinstance(admin, str):
            admin = gpd.read_file(admin)

        admin.to_crs(self.gdf.crs, inplace=True)

        self.gdf = gpd.sjoin(self.gdf, admin[[column_name, 'geometry']], how="inner", op='intersects')
        self.gdf.drop('index_right', axis=1, inplace=True)
        self.gdf.sort_index(inplace=True)

    def lives_saved(self):
        self.gdf["deaths_avoided"] = self.gdf.apply(
            lambda row: self.techs[row['max_benefit_tech']].deaths_avoided[row.name], axis=1) * self.gdf["Households"]

    def health_costs_saved(self):

        self.gdf["health_costs_avoided"] = self.gdf.apply(
            lambda row: self.techs[row['max_benefit_tech']].distributed_morbidity[row.name] +
                        self.techs[row['max_benefit_tech']].distributed_mortality[row.name], axis=1) * self.gdf["Households"]

    def extract_time_saved(self):
        self.gdf["time_saved"] = self.gdf.apply(lambda row: self.techs[row['max_benefit_tech']].total_time_saved[row.name], axis=1) * \
                                 self.gdf["Households"]

    def reduced_emissions(self):

        self.gdf["reduced_emissions"] = self.gdf.apply(
            lambda row: self.techs[row['max_benefit_tech']].decreased_carbon_emissions, axis=1) * self.gdf["Households"]

    def investment_costs(self):

        self.gdf["investment_costs"] = self.gdf.apply(
            lambda row: self.techs[row['max_benefit_tech']].discounted_investments, axis=1) * self.gdf["Households"]

    def om_costs(self):

        self.gdf["om_costs"] = self.gdf.apply(
            lambda row: self.techs[row['max_benefit_tech']].discounted_om_costs, axis=1) * self.gdf["Households"]

    def fuel_costs(self):

        self.gdf["fuel_costs"] = self.gdf.apply(
            lambda row: self.techs[row['max_benefit_tech']].discounted_fuel_cost[row.name], axis=1) * self.gdf["Households"]

    def emissions_costs_saved(self):

        self.gdf["emissions_costs_saved"] = self.gdf.apply(
            lambda row: self.techs[row['max_benefit_tech']].decreased_carbon_costs, axis=1) * self.gdf["Households"]

    def gdf_to_csv(self, scenario_name):

        name = os.path.join(self.output_directory, scenario_name)

        pt = self.gdf.to_crs({'init': 'EPSG:3395'})

        pt["X"] = pt["geometry"].x
        pt["Y"] = pt["geometry"].y

        df = pd.DataFrame(pt.drop(columns='geometry'))
        df.to_csv(name)

    def extract_wealth_index(self, wealth_index, file_type="csv", x_column="longitude", y_column="latitude",
                             wealth_column="rwi"):

        if file_type == "csv":
            df = pd.read_csv(wealth_index)

            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[x_column], df[y_column]))
            gdf.crs = 4326
            gdf.to_crs(self.gdf.crs, inplace=True)

            s1_arr = np.column_stack((self.gdf.centroid.x, self.gdf.centroid.y))
            s2_arr = np.column_stack((gdf.centroid.x, gdf.centroid.y))

            def do_kdtree(combined_x_y_arrays, points):
                mytree = scipy.spatial.cKDTree(combined_x_y_arrays)
                dist, indexes = mytree.query(points)
                return dist, indexes

            results1, results2 = do_kdtree(s2_arr, s1_arr)
            self.gdf["relative_wealth"] = gdf.loc[results2][wealth_column].values

        elif file_type == "point":
            gdf = gpd.read_file(wealth_index)
            gdf.to_crs(self.gdf.crs, inplace=True)

            s1_arr = np.column_stack((self.gdf.centroid.x, self.gdf.centroid.y))
            s2_arr = np.column_stack((gdf.centroid.x, gdf.centroid.y))

            def do_kdtree(combined_x_y_arrays, points):
                mytree = scipy.spatial.cKDTree(combined_x_y_arrays)
                dist, indexes = mytree.query(points)
                return dist, indexes

            results1, results2 = do_kdtree(s2_arr, s1_arr)
            self.gdf["relative_wealth"] = gdf.loc[results2].reset_index()[wealth_column]

        elif file_type == "polygon":
            gdf = gpd.read_file(wealth_index)
            gdf.to_crs(self.gdf.crs, inplace=True)

            gdf.rename(columns={wealth_column: "relative_wealth"})

            self.gdf = gpd.sjoin(self.gdf, gdf["relative_wealth"], how="inner", op='intersects')
        elif file_type == "raster":
            layer = RasterLayer('Demographics', 'Wealth', layer_path=wealth_index, resample='average')

            layer.align(self.base_layer.path)

            self.raster_to_dataframe(layer.layer, name="relative_wealth", method='read')
        else:
            raise ValueError("file_type needs to be either csv, raster, polygon or point.")

    def _create_layer(self, variable):
        layer = self.base_layer.layer.copy()
        tech_codes = None
        if isinstance(self.gdf[variable].iloc[0], str):
            dff = self.gdf.copy().reset_index(drop=False)
            dff[variable] += ' and '
            dff = dff.groupby('index').agg({variable: 'sum'})
            dff[variable] = [s[0:len(s) - 5] for s in dff[variable]]
            tech_codes = {tech: i for i, tech in enumerate(dff[variable].unique())}
            layer[self.rows, self.cols] = [tech_codes[tech] for tech in dff[variable]]
        else:
            dff = self.gdf.copy().reset_index(drop=False)
            dff = dff.groupby('index').agg({variable: 'sum'})
            layer[self.rows, self.cols] = dff[variable]
        raster = RasterLayer('Output', variable)
        raster.layer = layer

        return raster, tech_codes

    def to_raster(self, variable):
        raster, tech_codes = self._create_layer(variable)
        raster.meta = self.base_layer.meta
        raster.save(os.path.join(self.output_directory, 'Output'))
        print(f'Layer saved in {os.path.join(self.output_directory, "Output", variable + ".tif")}\n')
        if tech_codes:
            print('Variable codes:')
            for tech, value in tech_codes.items():
                print('    ' + tech + ':', value)
            print('')

    def plot(self, variable, cmap='viridis', cumulative_count=None, legend_position=(1.05, 1),
             admin_layer=None):
        raster, tech_codes = self._create_layer(variable)
        raster.bounds = self.base_layer.bounds
        if isinstance(admin_layer, gpd.GeoDataFrame):
            admin_layer = admin_layer
        elif not admin_layer:
            admin_layer = self.mask_layer.layer
        return raster.plot(cmap=cmap, cumulative_count=cumulative_count,
                           categories=tech_codes, legend_position=legend_position,
                           admin_layer=admin_layer)

    def to_image(self, variable, cmap='viridis', cumulative_count=None, legend_position=(1.05, 1),
                 admin_layer=None):
        raster, tech_codes = self._create_layer(variable)
        raster.bounds = self.base_layer.bounds
        if isinstance(admin_layer, gpd.GeoDataFrame):
            admin_layer = admin_layer
        elif not admin_layer:
            admin_layer = self.mask_layer.layer
        raster.save_png(self.output_directory, cmap=cmap, cumulative_count=cumulative_count,
                        categories=tech_codes, legend_position=legend_position,
                        admin_layer=admin_layer)
