from typing import List, Tuple, Union

import os
import pickle
import numpy as np
import pandas as pd
import scipy.optimize as opt
#from sklearn.preprocessing import RobustScaler

from .io_functions import save_dataframe_list


def transform_array_numpy(y, translation_dict):
    translation_func = np.vectorize(translation_dict.get)
    return translation_func(y)

def get_label_filters_for_all_cutoffs(y_df, length_df, all_cutoffs, remove_missing=False, missing_df=None, uncertain_filter=[5]):
    

    uncertain_filter = np.isin(y_df["label"], uncertain_filter)
    
    partial_filter = {}
    #Procedure is non-inclusive on lower cutoff
    for cutoffs in all_cutoffs:
        low_cutoff, high_cutoff = cutoffs
        
        partial_filter[str(cutoffs)] = np.logical_and(length_df["lengths"] > low_cutoff, length_df["lengths"] <= high_cutoff)
        
    full_filters = {}
    for cutoffs in all_cutoffs:
        other_cutoffs = list(set(all_cutoffs).difference(set([cutoffs])))
        
        other_partial_filters = [partial_filter[str(c)] for c in other_cutoffs]
        
        length_filter= np.logical_or.reduce(other_partial_filters)
        
        if remove_missing:
            missing_filter = missing_df["missing"] != 0
            full_filters[str(cutoffs)] = np.logical_or.reduce([uncertain_filter, length_filter, missing_filter])
        else:
            full_filters[str(cutoffs)] = np.logical_or(uncertain_filter, length_filter)
        
    return full_filters

def get_event_lengths(y_df):
    
        lengths = np.zeros(len(y_df))
        
        event_started = False
        event_start_index = None
        
        for i in range(len(y_df)):
            
            
            if event_started:
                
                #Event ends
                if y_df["label"][i] != 1:
                    event_end_index = i #not inclusive
                    
                    lengths[event_start_index:event_end_index] = event_end_index-event_start_index
                    event_started = False
                #Event continues
                else:
                    pass
            else:
                #Event starts
                if y_df["label"][i] == 1:
                    event_start_index = i
                    event_started = True
                #Event has not started:
                else:
                    pass
                
        #if event has not ended at end of timeseries:
        if event_started:
            event_end_index = i+1 #not inclusive
            
            lengths[event_start_index:event_end_index] = event_end_index-event_start_index
        return pd.DataFrame({"lengths":lengths})


def find_subsequent_duplicates(y, subsequent_duplicates):
    n = len(y)
    subsequent_filter = np.zeros((n,))

    if n < 2 or subsequent_duplicates < 1:
        return subsequent_filter  # No subsequent duplicates possible

    count = 1  # Initialize count for the first element
    for i in range(1, n):
        if y[i] == y[i - 1]:
            count += 1
        else:
            count = 1  # Reset count if the current element is different

        if count >= subsequent_duplicates:
            for j in range(i - count + 1, i + 1):
                subsequent_filter[j] = 1  # Set subsequent_filter to 1 for the repeating elements

    return subsequent_filter

def preprocess_data(X_df: pd.DataFrame, y_df: pd.DataFrame, subsequent_nr: int, lin_fit_quantiles: tuple, label_transform_dict: dict, remove_uncertain: bool, rescale_S_to_kW=False) -> pd.DataFrame:
    """Match bottom up with substation measurements with linear regression and apply the sign value to the substation measurements.

    Args:
        df (pd.DataFrame): Dataframe with at least the columns M_TIMESTAMP, S_original, BU_original and Flag.
        subsequent_nr (int): Integer that represents the number of subsequent equal measurements
        line_fit_quantiles (tuple): A tuple containing the lower and upper quantiles for the linear fit model

    Returns:
        pd.DataFrame: DataFrame with the columns M_TIMESTAMP, S_original, BU_original, diff_original, S, BU, diff, and missing.
    """ 
    
    #set copy on write option in pandas:
    
    pd.options.mode.copy_on_write = True
    X_df = X_df.copy()
    y_df = y_df.copy()
    
    #X_df = add_time_features(X_df)
        
    # Calculate difference and add label column.
    if rescale_S_to_kW:
        X_df["S_original"] = X_df["S_original"] * 1000
        
    X_df['diff_original'] = X_df['S_original']-X_df['BU_original']
        
    # Flag measurement mistakes BU and SO
    # 0 okay
    # 1 measurement missing
    # 2 bottom up missing
    
    X_df['S'] = X_df['S_original'].copy()
    
    #If no "missing" column is supplied, construct one based on set criteria (missing BU or repeating measurements (based on subsequent_nr))
    if not "missing" in X_df.columns:
        X_df['missing'] = 0    
    
    X_df.loc[X_df['BU_original'].isnull(),'missing'] = 1
    X_df.loc[X_df['S_original'].isnull(),'missing'] = 1
        
    subsequent_filter = find_subsequent_duplicates(X_df["S"], subsequent_nr)
    
    X_df['missing'] = np.logical_or(X_df["missing"], subsequent_filter)
    
    #Transform labels so that they are only [0,1,5] for [normal, anomalouos, uncertain]
    y_df.loc[np.logical_not(y_df["label"].isnull()), "label"] = transform_array_numpy(y_df.loc[np.logical_not(y_df["label"].isnull()), "label"], label_transform_dict)
    
    if remove_uncertain:
        uncertain_filter = y_df["label"] != 5
        X_df = X_df.loc[uncertain_filter,:]
        y_df = y_df.loc[uncertain_filter,:]
    
    # Match bottom up with substation measurements for the middle N% of the values and apply sign to substation measurements
    
    arr = X_df[X_df['missing']==0].copy()
    
    low_quant, up_quant = lin_fit_quantiles
    low_quant_value = np.percentile(arr['diff_original'],low_quant)
    up_quant_value = np.percentile(arr['diff_original'],up_quant)
    
    arr = arr[np.logical_and(arr['diff_original'] > low_quant_value, arr['diff_original'] < up_quant_value)]
    
    a, b = match_bottomup_load(bottomup_load=arr['BU_original'], measurements=arr['S_original'])
    X_df.loc[:,'BU'] = a*X_df['BU_original']+b
    if X_df['S_original'].min()>=0 and X_df['BU_original'].iloc[X_df['S_original'].argmin()] < 0:
        X_df['S'] = np.sign(X_df['BU'])*X_df['S']
    X_df.loc[:,'diff'] = X_df['S']-X_df['BU']
        
    # remove all diff NaN in X and y
    y_df = y_df[X_df['diff'].notna()]
    X_df = X_df[X_df['diff'].notna()]
    
    # reset index of dfs
    y_df = y_df.reset_index()
    X_df = X_df.reset_index()
    
    
    
    return X_df[['M_TIMESTAMP', 
               'S_original', 'BU_original', 'diff_original', 
               'S', 'BU', 'diff', 'missing']], y_df
              


def match_bottomup_load(bottomup_load: Union[pd.Series, np.ndarray], measurements: Union[pd.Series, np.ndarray]) -> Tuple[int]:
    """Match bottom up with substation measurements with linear regression and apply the sign value to the substation measurements.

    Args:
        bottomup_load (Union[pd.Series, np.ndarray]): Contains the bottom up load of a substation.
        measurements (Union[pd.Series, np.ndarray]): Contains the measured load of a substation.

    Returns:
        Tuple[int, int]: Optimized parameter a, used to multiply the bottom up load and optimized parameter b, used to add to the bottom up load.
    """
    def calculate_ab(ab: List[int], bottomup_load: Union[pd.Series, np.ndarray], measurements: Union[pd.Series, np.ndarray]):
        a, b  = ab
        if min(measurements) < 0:
            return np.sum(((a*bottomup_load+b)-measurements)**2)

        return np.sum((abs(a*bottomup_load+b)-measurements)**2)

    #Optimize a and b variables of linear regression.
    ab_initial = [1,0] #initial guess: bottomup_load is correct --> a=1, b=0
    ab = opt.minimize(calculate_ab, x0=ab_initial, args=(bottomup_load, measurements))

    #Use a and b to calculate new bottom up load and adjusted measurements.
    a, b = ab.x
    return a, b

def preprocess_per_batch_and_write(X_dfs, y_dfs, intermediates_folder, which_split, preprocessing_overwrite, write_csv_intermediates, file_names, all_cutoffs, hyperparameters, hyperparameter_hash, remove_missing=False, dry_run=False):
    #Set preprocessing settings here:
    preprocessed_pickles_folder = os.path.join(intermediates_folder, "preprocessed_data_pickles", which_split)
    preprocessed_csvs_folder = os.path.join(intermediates_folder, "preprocessed_data_csvs", which_split)
    
    # ensures preprocessing with different hyperparameters is saved in different folders
    
    preprocessed_file_name_X = os.path.join(preprocessed_pickles_folder, hyperparameter_hash + "_X.pickle")
    preprocessed_file_name_y = os.path.join(preprocessed_pickles_folder, hyperparameter_hash + "_y.pickle")
    
    if preprocessing_overwrite or not os.path.exists(preprocessed_file_name_X):
        print("Preprocessing X and y data")
        dfs_preprocessed = [preprocess_data(X_df, y_df, **hyperparameters) for (X_df, y_df) in zip(X_dfs, y_dfs)]
        
        X_dfs_preprocessed = [X_df for (X_df, y_df) in dfs_preprocessed]
        y_dfs_preprocessed = [y_df for (X_df, y_df) in dfs_preprocessed]
        
        if not dry_run:
            os.makedirs(preprocessed_pickles_folder, exist_ok = True)
            with open(preprocessed_file_name_X, 'wb') as handle:
                pickle.dump(X_dfs_preprocessed, handle)
            with open(preprocessed_file_name_y, 'wb') as handle:
                pickle.dump(y_dfs_preprocessed, handle)
    else:
        print("Loading preprocessed X data")
        with open(preprocessed_file_name_X, 'rb') as handle:
            X_dfs_preprocessed = pickle.load(handle)
        print("Loading preprocessed y data")
        with open(preprocessed_file_name_y, 'rb') as handle:
            y_dfs_preprocessed = pickle.load(handle)
        
    
    if write_csv_intermediates and not dry_run:
        print("Writing CSV intermediates: X data")
        type_preprocessed_csvs_folder = os.path.join(preprocessed_csvs_folder, hyperparameter_hash)
        
        type_preprocessed_csvs_folder_X = os.path.join(type_preprocessed_csvs_folder, "X")
        type_preprocessed_csvs_folder_y = os.path.join(type_preprocessed_csvs_folder, "y")
        
        save_dataframe_list(X_dfs_preprocessed, file_names, type_preprocessed_csvs_folder_X, overwrite = preprocessing_overwrite)
        save_dataframe_list(y_dfs_preprocessed, file_names, type_preprocessed_csvs_folder_y, overwrite = preprocessing_overwrite)

    #Preprocess Y_data AKA get the lengths of each event
    event_lengths_pickles_folder = os.path.join(intermediates_folder, "event_length_pickles", which_split)
    event_lengths_csvs_folder = os.path.join(intermediates_folder, "event_length_csvs", which_split)

    preprocessed_file_name = os.path.join(event_lengths_pickles_folder, hyperparameter_hash + ".pickle")
    if preprocessing_overwrite or not os.path.exists(preprocessed_file_name):
        print("Preprocessing event lengths")
        event_lengths = [get_event_lengths(df) for df in y_dfs_preprocessed]
        
        if not dry_run:
            os.makedirs(event_lengths_pickles_folder, exist_ok = True)
            with open(preprocessed_file_name, 'wb') as handle:
                pickle.dump(event_lengths, handle)
    else:
        print("Loading preprocessed event lengths")
        with open(preprocessed_file_name, 'rb') as handle:
            event_lengths = pickle.load(handle)

    if write_csv_intermediates and not dry_run:
        print("Writing CSV intermediates: event lengths")
        type_event_lengths_csvs_folder = os.path.join(event_lengths_csvs_folder, hyperparameter_hash)
        save_dataframe_list(event_lengths, file_names, type_event_lengths_csvs_folder, overwrite = preprocessing_overwrite)


    # Use the event lengths to get conditional label filters per cutoff
    label_filters_per_cutoff_pickles_folder = os.path.join(intermediates_folder, "label_filters_per_cutoff_pickles", which_split)
    label_filters_per_cutoff_csvs_folder = os.path.join(intermediates_folder, "label_filters_per_cutoff_csvs", which_split)

    preprocessed_file_name = os.path.join(label_filters_per_cutoff_pickles_folder, hyperparameter_hash + ".pickle")
    if preprocessing_overwrite or not os.path.exists(preprocessed_file_name):
        print("Preprocessing labels per cutoff")
        label_filters_for_all_cutoffs = [get_label_filters_for_all_cutoffs(y_df, length_df, all_cutoffs, remove_missing=remove_missing, missing_df=X_df) for y_df, length_df, X_df in zip(y_dfs_preprocessed, event_lengths, X_dfs_preprocessed)]
        
        if not dry_run:
            os.makedirs(label_filters_per_cutoff_pickles_folder, exist_ok = True)
            with open(preprocessed_file_name, 'wb') as handle:
                pickle.dump(label_filters_for_all_cutoffs, handle)
    else:
        print("Loading preprocessed labels per cutoff")
        with open(preprocessed_file_name, 'rb') as handle:
            label_filters_for_all_cutoffs = pickle.load(handle)

    if write_csv_intermediates and not dry_run:
        print("Writing CSV intermediates: label filters per cutoff")
        type_label_filters_per_cutoff_csvs_folder = os.path.join(label_filters_per_cutoff_csvs_folder, hyperparameter_hash)
        label_filters_for_all_cutoffs_dfs = [pd.DataFrame(l) for l in label_filters_for_all_cutoffs]
        save_dataframe_list(label_filters_for_all_cutoffs_dfs, file_names, type_label_filters_per_cutoff_csvs_folder, overwrite = preprocessing_overwrite)
        
    
    return X_dfs_preprocessed, y_dfs_preprocessed, label_filters_for_all_cutoffs, event_lengths