#! /bin/python
"""
This class implements the dto interface for the  data validation.
"""
from typing import TypeVar
import pandas as pd
import numpy as np
#------------------------------------------- Use This Class for Chargeup Parquet Format data-----------------------------------------------     ----------------
import pandas as pd

class dto_ness_parquet:
    def __init__(self, df):
        # Create new columns directly in the input df (ic, id, tmp)
        input_cols= ['timestamp', 'Ip', 'Vp', 'SoC', 'Q', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6',
       'V7', 'V8', 'V9', 'V10', 'V11', 'V12', 'V13', 'V14', 'V15', 'V16',
       'BPackID', 'FullCap', 'BalStat', 'SoH', 'CyCnt', 'Vbus', 'Tamb',
       'MOSstate', 'HwErr', 'Err', 'Warn', 'BT1', 'BT2', 'BT3', 'BT4',
       'BMSArrId', 'Tpow', 'SysState', 'DisconStat']
        
        
        float_cols=['timestamp','Ip', 'Vp', 'SoC', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6',
       'V7', 'V8', 'V9', 'V10', 'V11', 'V12', 'V13', 'V14', 'V15', 'V16', 'SoH','BT1', 'BT2', 'BT3', 'BT4','CyCnt','FullCap']
        selected_float_cols = list(set(float_cols).intersection(set(df.columns)))
        df[selected_float_cols] = df[selected_float_cols].astype(float, errors='ignore')
        
        volt_cols = ['V1', 'V2', 'V3', 'V4', 'V5', 'V6',
       'V7', 'V8', 'V9', 'V10', 'V11', 'V12', 'V13', 'V14', 'V15', 'V16']
        df = self.merge_cols(df)
        self.df = self.add_custom_columns(df)
        
        
        
        # Mapping of input columns to required columns
        self.column_mapping = {
            'timestamp': 'ts', 'Ip': 'Ip', 'Vp': 'lv', 'SoC': 'soc',
            'tmp': 'tmp', 'SoH': 'soh', 'V1': 'strv_1', 'V2': 'strv_2',
            'V3': 'strv_3', 'V4': 'strv_4', 'V5': 'strv_5', 'V6': 'strv_6',
            'V7': 'strv_7', 'V8': 'strv_8', 'V9': 'strv_9', 'V10': 'strv_10',
            'V11': 'strv_11', 'V12': 'strv_12', 'V13': 'strv_13', 'V14': 'strv_14',
            'V15': 'strv_15', 'V16': 'strv_16','CyCnt':'CyCnt', 'FullCap': 'FullCap',
            'BT1': 'BT1', 'BT2': 'BT2', 'BT3': 'BT3', 'BT4': 'BT4'
        }
        
        # Required columns after mapping
        self.required_columns = ['ts', 'ic', 'id', 'lv', 'soc', 'tmp', 'soh', 'strv_1', 'strv_2', 'strv_3', 
                                 'strv_4', 'strv_5', 'strv_6', 'strv_7', 'strv_8', 'strv_9', 'strv_10', 
                                 'strv_11', 'strv_12', 'strv_13', 'strv_14', 'strv_15', 'strv_16','CyCnt','FullCap',
                                 'BT1', 'BT2', 'BT3', 'BT4']

        # Perform the mapping of columns
        self.df = self.map_columns(self.df)
        self.df = self.drop_empty_or_zero_columns(self.df)

    def add_custom_columns(self, df):
        # Handle missing values in Ip: ic and id will be NaN if Ip is NaN
        df['ic'], df['id'] = zip(*df['Ip'].apply(lambda ip: (np.nan, np.nan) if pd.isna(ip) else self.compute_ic_id(ip)))

        # Define the temperature columns
        temp_columns = {'BT1', 'BT2', 'BT3', 'BT4'}

        # Determine which temperature columns are available in the DataFrame
        available_temp_columns = list(temp_columns.intersection(df.columns))

        if available_temp_columns:
            for col in available_temp_columns:
                df[col] = df[col] / 10
            df['tmp'] = df[available_temp_columns].max(axis=1, skipna=True)
        else:
            df['tmp'] = pd.NA

        return df
    def merge_cols(self,df):
       df=df.sort_values(by='timestamp')
       cols_list1  = ['Ip','Vp','SoC','SoH','CyCnt','FullCap']
       cols_list2 = [ 'V1', 'V2', 'V3', 'V4', 'V5', 'V6',
                     'V7', 'V8', 'V9', 'V10', 'V11', 'V12', 'V13', 'V14', 'V15', 'V16','BT1','BT2','BT3','BT4']
       selected_cols_list1 = list(set(cols_list1).intersection(set(df.columns)))
       selected_cols_list2 = list(set(cols_list2).intersection(set(df.columns)))
       df1      = df[['timestamp']+selected_cols_list1].dropna(subset=selected_cols_list1,how='all')
       df2      = df[['timestamp']+selected_cols_list2].dropna(subset=selected_cols_list2,how='all')
       df = pd.merge_asof(
                                   df1,   # Current not NaN
                                   df2,   # Voltage not NaN
                                   on='timestamp',
                                   direction='nearest'
                                )
       return df

    def map_columns(self, df):
        # Rename columns based on the mapping
        df_mapped = df.rename(columns=self.column_mapping)
        
        # Add any missing required columns with NaN values
        for col in self.required_columns:
            if col not in df_mapped.columns:
                df_mapped[col] = pd.NA
        
        # Reorder columns to match the required order
        df_mapped = df_mapped[self.required_columns]
        
        return df_mapped
    
    
    
    @staticmethod
    def compute_ic_id(ip_value):
        if ip_value > 0:
            return 0, abs(ip_value)  # ic is 0, id is abs(Ip)
        elif ip_value < 0:
            return abs(ip_value), 0  # ic is abs(Ip), id is 0
        else:
            return 0, 0  # both ic and id are 0
    
    def drop_empty_or_zero_columns(self, df):
        """
        Drop columns that are entirely NaN or 0 (NaN + 0 only)
        """
        numeric_df = df.select_dtypes(include='number')

        cols_to_drop = numeric_df.columns[
            numeric_df.fillna(0).eq(0).all()
        ]
        return df.drop(columns=cols_to_drop)

#===============================================================================================================================================================

    
        
       

    



        