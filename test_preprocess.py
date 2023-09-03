#%% Load packages
import os

import numpy as np
import pandas as pd
import ruptures as rpt
import matplotlib.pyplot as plt


from src.methods import SingleThresholdStatisticalProfiling
from src.preprocess import preprocess_per_batch_and_write
from src.io_functions import save_dataframe_list, load_batch

from src.preprocess import match_bottomup_load


#%% load data

data_folder = "data"

which_split = "Train"
X_train_dfs, y_train_dfs, X_train_files= load_batch(data_folder, which_split)

#%% def functions

def test_preprocess(df: pd.DataFrame) -> pd.DataFrame:
    """Match bottom up with substation measurements with linear regression and apply the sign value to the substation measurements.

    Args:
        df (pd.DataFrame): Dataframe with at least the columns M_TIMESTAMP, S_original, BU_original and Flag.

    Returns:
        pd.DataFrame: DataFrame with the columns M_TIMESTAMP, S_original, BU_original, diff_original, S, BU, diff, and missing.
    """
    
    # Calculate difference and add label column.
    df['diff_original'] = df['S_original']-df['BU_original']
        
    # Flag measurement mistakes BU and SO
    # 0 okay
    # 1 measurement missing
    # 2 bottom up missing
    # Flag measurement as missing when 5 times after each other the same value expect 0
    df['S'] = df['S_original'].copy()
    df['missing'] = 0
    df.loc[df['BU_original'].isnull(),'missing'] = 2
    
    prev_v = 0
    prev_i = 0
    # make it a hyperparameter
    count = 5
    
    for i, v in enumerate(df['S']):
        # if value is same as previous, decrease count by 1
        if v == prev_v:
            count -= 1
            continue
            
        # if not, check if previous count below zero, if so, set all missing values to 1
        elif count <= 0:
            df.loc[prev_i:i - 1, 'missing'] = 1
            
        # reset vars
        prev_v = v
        prev_i = i
        count = 5 #use hyperparameter
    
    # Match bottom up with substation measurements for the middle 80% of the values and apply sign to substation measurements
    arr = df[df['missing']==0]
    arr = arr[(arr['diff_original'] > np.percentile(arr['diff_original'],10)) & (arr['diff_original'] < np.percentile(arr['diff_original'],90))]
    
    a, b = match_bottomup_load(bottomup_load=arr['BU_original'], measurements=arr['S_original'])
    df['BU'] = a*df['BU_original']+b
    if df['S_original'].min()>0:
        df['S'] = np.sign(df['BU'])*df['S']
    df['diff'] = df['S']-df['BU']
    
    
    return df[['M_TIMESTAMP', 
               'S_original', 'BU_original', 'diff_original', 
               'S', 'BU', 'diff', 
               'missing']]


def data_to_score(df, bkps):
    y_score = np.zeros(len(df))
    total_mean = np.mean(df) # calculate mean of all values in timeseries
    
    prev_bkp = 0
        
    for bkp in bkps:
        segment = df[prev_bkp:bkp] # define a segment between two breakpoints
        segment_mean = np.mean(segment)
        
        # for all values in segment, set its score to th difference between the total mean and the mean of the segment its in
        y_score[prev_bkp:bkp] = total_mean - segment_mean   
        
        prev_bkp = bkp
    
    return y_score   

#%% 

"""
# check which files have NaN values

for i, df in enumerate(X_train_dfs):
    if df["BU_original"].isna().sum() != 0:
        print(X_train_files[i])
"""


df = X_train_dfs[48]
signal = np.array(df['S_original']-df['BU_original'])

n = len(signal) # nr of samples
sigma = np.std(signal) * 3 #noise standard deviation

# hyperparameters
model = "l1"
min_size = 100
jump = 10
penalty = np.log(n) * sigma**2

# detection
algo = rpt.Binseg(model=model, min_size=min_size, jump=jump)
result = algo.fit_predict(signal, pen = penalty)

# display
rpt.display(signal, result)
plt.show()



    
    