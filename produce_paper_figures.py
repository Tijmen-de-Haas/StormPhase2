#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Oct 29 17:58:43 2023

@author: rbouman
"""

#This script reproduces all figures from the paper.
#%% package loading
import os
import pickle
import jsonpickle
import sqlite3

import pandas as pd
import numpy as np

import matplotlib.pyplot as plt
import seaborn as sns

from hashlib import sha256


from src.plot_functions import plot_S_original, plot_BU_original, plot_predictions
from src.io_functions import load_PRFAUC_table, load_batch, load_dataframe_list

from src.methods import SingleThresholdStatisticalProcessControl
from src.methods import DoubleThresholdStatisticalProcessControl
from src.methods import SingleThresholdIsolationForest

from src.methods import SingleThresholdBinarySegmentation
from src.methods import DoubleThresholdBinarySegmentation

from src.methods import StackEnsemble
from src.methods import NaiveStackEnsemble

from src.preprocess import preprocess_per_batch_and_write

sns.set()

#%% Data loading

dataset = "OS_data" #alternatively: route_data
data_folder = os.path.join("data", dataset)
result_folder = os.path.join("results", dataset)
intermediates_folder = os.path.join("intermediates", dataset)
model_folder = os.path.join("saved_models", dataset)

table_folder = os.path.join("Tables", dataset)
figure_folder = os.path.join("Figures", dataset)

os.makedirs(table_folder, exist_ok=True)
os.makedirs(figure_folder, exist_ok=True)

score_folder = os.path.join(result_folder, "scores")
predictions_folder = os.path.join(result_folder, "predictions")
metric_folder = os.path.join(result_folder, "metrics")

all_cutoffs = [(0, 24), (24, 288), (288, 4032), (4032, np.inf)]

train_name = "Train"
test_name = "Test"
validation_name = "Validation"

all_dataset_names = [train_name, test_name, validation_name]

#%% connect to database

DBFILE = "experiment_results.db"
database_exists = os.path.exists(DBFILE)

db_connection = sqlite3.connect(DBFILE) # implicitly creates DBFILE if it doesn't exist
db_cursor = db_connection.cursor()

#%% replace cutoff by category:
cutoff_replacement_dict = {"(0, 24)":"1-24", "(24, 288)":"25-288","(288, 4032)":"288-4032", "(4032, inf)":"4033 and longer"}

#%% Visualize/tabularize input data and preprocessing

#measurement_example.pdf
station_ID = "019"

n_xlabels = 10

train_IDs = os.listdir(os.path.join(data_folder, "Train", "X"))
test_IDs = os.listdir(os.path.join(data_folder, "Test", "X"))
validation_IDs = os.listdir(os.path.join(data_folder, "Validation", "X"))

all_station_IDs = train_IDs + test_IDs + validation_IDs

train_ID_dict = {ID.replace(".csv", ""): "Train" for ID in train_IDs}
test_ID_dict = {ID.replace(".csv", ""): "Test" for ID in test_IDs}
validation_ID_dict = {ID.replace(".csv", ""): "Validation" for ID in validation_IDs}

#fastest dict merge: https://stackoverflow.com/questions/1781571/how-to-concatenate-two-dictionaries-to-create-a-new-one
station_dataset_dict = dict(train_ID_dict, **test_ID_dict)
station_dataset_dict.update(validation_ID_dict)

X_df = pd.read_csv(os.path.join(data_folder, station_dataset_dict[station_ID], "X", station_ID + ".csv"))
y_df = pd.read_csv(os.path.join(data_folder, station_dataset_dict[station_ID], "y", station_ID + ".csv"))


fig = plt.figure(figsize=(30,16)) # add DPI=300+ in case some missing points don't show up'    
plt.title("Station: " + station_ID, fontsize=60)


plot_S_original(X_df, label="S original")
plot_BU_original(X_df, label="BU original")

plt.legend(fontsize=30)

plt.yticks(fontsize=30)
plt.ylabel("S", fontsize=30)

ticks = np.linspace(0,len(X_df["S_original"])-1, n_xlabels, dtype=int)
plt.xticks(ticks=ticks, labels=X_df["M_TIMESTAMP"].iloc[ticks], rotation=45, fontsize=30)
plt.xlim((0, len(X_df)))

plt.tight_layout()

plt.savefig(os.path.join(figure_folder, "measurement_example.pdf"), format="pdf")
plt.savefig(os.path.join(figure_folder, "measurement_example.png"), format="png")
plt.show()
#event_length_distribution.pdf, event_length_stats.tex
#Show as histogram and stats table
lengths = {}
for split_name in all_dataset_names:
    lengths_path = os.path.join(intermediates_folder, "event_length_pickles", split_name)
    length_pickle_path = os.path.join(lengths_path, os.listdir(lengths_path)[0]) #pick first folder, as it shouldn't matter for event length distribution

    with open(length_pickle_path, 'rb') as handle:
        lengths[split_name] = pickle.load(handle)

lengths["All"] = [df for dfs_list in lengths.values() for df in dfs_list]

normalized_length_count_per_cutoff_list = []
length_count_per_cutoff_list = []

for split in all_dataset_names+["All"]:
    concat_lengths = np.concatenate(lengths[split])
    
    unique_lengths, length_counts = np.unique(concat_lengths, return_counts=True)
    
    
    unique_lengths = unique_lengths[1:]
    length_counts = length_counts[1:]
    
    normalized_length_counts = []
    for unique_length, length_count in zip(unique_lengths, length_counts):#skip 0
        normalized_length_counts.append(length_count/unique_length)
        
    normalized_length_count_per_cutoff = {str(cutoff):0 for cutoff in all_cutoffs}
    length_count_per_cutoff = {str(cutoff):0 for cutoff in all_cutoffs}
    
    for unique_length, normalized_length_count, length_count in zip(unique_lengths,normalized_length_counts, length_counts):
        for cutoff in all_cutoffs:
            if unique_length >= cutoff[0] and unique_length < cutoff[1]: 
                normalized_length_count_per_cutoff[str(cutoff)] += normalized_length_count
                length_count_per_cutoff[str(cutoff)] += length_count
                
    normalized_length_count_per_cutoff_list.append({key:[value][0] for key, value in normalized_length_count_per_cutoff.items()})
    length_count_per_cutoff_list.append({key:[value][0] for key, value in length_count_per_cutoff.items()})

event_length_stats = pd.concat([pd.DataFrame(normalized_length_count_per_cutoff_list), pd.DataFrame(length_count_per_cutoff_list)]).astype(int)
event_length_stats.index = pd.MultiIndex.from_product([["Event count", "Label $1$ count"], list(lengths.keys())], names=["", "Dataset"])
    
    
event_length_stats.rename(columns=cutoff_replacement_dict, inplace=True)
event_length_stats.to_latex(buf=os.path.join(table_folder, "event_length_stats.tex"), escape=False, multirow=True)

lengths_to_hist = []
for unique_length, normalized_length_count in zip(unique_lengths, normalized_length_counts):
    lengths_to_hist += [unique_length]*int(normalized_length_count)

plt.figure()
plt.hist(lengths_to_hist, bins=100)
plt.yscale('log')
plt.xlabel("Event Length (#data points)")
plt.ylabel("Counts (log)")
plt.savefig(os.path.join(figure_folder, "event_length_distribution.pdf"), format="pdf")
plt.savefig(os.path.join(figure_folder, "event_length_distribution.png"), format="png")
plt.show()

#%% Visualize threshold optimization strategy


#load model:
preprocessing_hash = "10cab9fc324db7a2fd5d8674c71edb68908b5e572ffa442d201eb0ca0aa288e1"
hyperparameter_hash = "863c7a1a49f110ada1d11bf21549b9f60f53c72042a80a36a0969583a18d42e1"

db_result = db_cursor.execute("SELECT method_hyperparameters FROM experiment_results WHERE preprocessing_hash='{}' AND hyperparameter_hash='{}'".format(preprocessing_hash, hyperparameter_hash)).fetchone()[0]

hyperparameters = jsonpickle.loads(db_result)

from src.evaluation import f_beta
from src.methods import SingleThresholdStatisticalProcessControl
beta = 1.5
def score_function(precision, recall):
    return f_beta(precision, recall, beta)


model = SingleThresholdStatisticalProcessControl(model_folder, preprocessing_hash, **hyperparameters, score_function=score_function)
model.calculate_and_set_thresholds(all_cutoffs, score_function)

plt.figure()

category_labels = ["1-24", "25-288", "289-4032", "4033 and longer"]
colors = sns.color_palette()[:3] + [sns.color_palette()[4]]
thresholds = model.thresholds
for i, column in enumerate(model.scores.columns):
    scores = model.scores[column]
    
    plt.plot(thresholds, scores, label=category_labels[i], linestyle=":", color=colors[i])
    
plt.plot(thresholds, np.mean(model.scores, axis=1), label="average", color=sns.color_palette()[3])

plt.axvline(x = model.optimal_threshold, color = sns.color_palette()[3], linestyle="--", label = 'optimal threshold')

plt.legend()
plt.xlabel("Threshold")
plt.ylabel("F1.5")
plt.xlim((0, 4)) #hardcoded
plt.savefig(os.path.join(figure_folder, "threshold_optimization.pdf"), format="pdf")
plt.savefig(os.path.join(figure_folder, "threshold_optimization.png"), format="png")
plt.show()

#%% summarize results on validation set for each method
#show for each method:
    # validation average F1.5
    # validation F1.5 for each cutoff/category
    # validation average ROC/AUC (optional?)
    # best preprocessing hyperparameters (optional?)
    # best hyperparameters (optional?)

#TODO: Technically, we shouldn't select MAX(metric) from Validation, but those hashes where MAX(metric) in Test (if we do 1 run over all hyperparameters, this is moot, but if we keep updating this might spell trouble)
validation_results = db_cursor.execute("SELECT method, preprocessing_hyperparameters, method_hyperparameters, MAX(metric), preprocessing_hash, hyperparameter_hash FROM experiment_results WHERE which_split='Validation' GROUP BY method").fetchall()
validation_results_and_metadata_df = pd.DataFrame(validation_results)
validation_results_and_metadata_df.columns = ["Method", "Preprocessing Hyperparameters", "Method Hyperparameters", "Average F1.5", "preprocessing_hash", "hyperparameter_hash"]
best_hyperparameter_df = validation_results_and_metadata_df.iloc[:,:3]
best_hyperparameter_df.set_index("Method", inplace=True)

for i in range(best_hyperparameter_df.shape[0]):
    #Treat ensembles differently:
    
    hyperparameters = jsonpickle.loads(best_hyperparameter_df["Method Hyperparameters"].iloc[i])
    if "method_classes" in hyperparameters: #if dict has method_classes, the method is an ensemble method
        method_dict = hyperparameters
        hyperparameter_strings = []
        for method, hyperparameters in zip(method_dict["method_classes"], method_dict["method_hyperparameter_dict_list"]):
            method_name = method("temp","temp").method_name
            hyperparameter_strings.append(method_name + ":" + str(hyperparameters))
        best_hyperparameter_df["Method Hyperparameters"].iloc[i] = "\n".join(hyperparameter_strings)
    else:
        hyperparameters.pop("used_cutoffs", None)
        best_hyperparameter_df["Method Hyperparameters"].iloc[i] = str(hyperparameters)
    preprocessing_hyperparameters = jsonpickle.loads(best_hyperparameter_df["Preprocessing Hyperparameters"].iloc[i])
    best_hyperparameter_df["Preprocessing Hyperparameters"].iloc[i] = str(preprocessing_hyperparameters)
    
with pd.option_context("display.max_colwidth", None):
    best_hyperparameter_df.to_latex(buf=os.path.join(table_folder, "best_hyperparameters.tex"), multirow=True)

#extended results:
full_validation_results = []
for i, row in validation_results_and_metadata_df.iterrows():
    #load PRFAUC table:
    method_name = row["Method"]
    preprocessing_hash = row["preprocessing_hash"]
    hyperparameter_hash = row["hyperparameter_hash"]
    PRFAUC_table_path = os.path.join(metric_folder, "PRFAUC_table", "Validation", method_name, preprocessing_hash)
    PRFAUC_table = load_PRFAUC_table(PRFAUC_table_path, hyperparameter_hash)
    PRFAUC_table.loc["Average", :] = PRFAUC_table.mean()
    
    index = [PRFAUC_table.index, [method_name]]
    index = pd.MultiIndex.from_product([[method_name], PRFAUC_table.index], names=["Method", "Length category"])
    
    PRFAUC_table.index = index
    
    full_validation_results.append(PRFAUC_table)
    #df_entry = 
full_validation_results_df = pd.concat(full_validation_results).round(3)
full_validation_results_df.rename(cutoff_replacement_dict, inplace=True)
full_validation_results_df.rename(columns={"precision":"Precision", "recall":"Recall","ROC/AUC":"AUC"}, inplace=True)


full_validation_results_df.to_latex(buf=os.path.join(table_folder, "full_validation_results.tex"), multirow=True)

#%% Visualize/tabularize segmentation results of different methods
methods = {"SingleThresholdSPC":SingleThresholdStatisticalProcessControl, "SingleThresholdIF":SingleThresholdIsolationForest}

preprocessing_overwrite=False 
write_csv_intermediates=False

which_split = "Validation"
print("Split: Validation")
X_val_dfs, y_val_dfs, X_val_files = load_batch(data_folder, which_split)
val_file_names = X_val_files

best_hyperparameters = {}
best_preprocessing_hyperparameters = {}
for method_name in methods:
    print("Now plotting: " + method_name)
    #find best preprocessing and method hyperparameters:

    #Some SQL query:
    
    best_model_entry = db_cursor.execute("SELECT e.* FROM experiment_results e WHERE e.metric = (SELECT MAX(metric)FROM experiment_results WHERE method = (?) AND which_split = (?))", (method_name, "Test"))
    
    (preprocessing_hash, hyperparameter_hash, _, _, preprocessing_hyperparameter_string_pickle, hyperparameter_string_pickle, _) = next(best_model_entry)
    
    best_hyperparameters[method_name] = jsonpickle.decode(hyperparameter_string_pickle)
    best_preprocessing_hyperparameters[method_name] = jsonpickle.decode(preprocessing_hyperparameter_string_pickle)

    preprocessing_hyperparameters = best_preprocessing_hyperparameters[method_name]
    preprocessing_hyperparameter_string = str(preprocessing_hyperparameters)
    preprocessing_hash = sha256(preprocessing_hyperparameter_string.encode("utf-8")).hexdigest()
    
    X_dfs_preprocessed, y_dfs_preprocessed, label_filters_for_all_cutoffs, event_lengths = preprocess_per_batch_and_write(X_val_dfs, y_val_dfs, intermediates_folder, which_split, preprocessing_overwrite, write_csv_intermediates, val_file_names, all_cutoffs, preprocessing_hyperparameters, preprocessing_hash)

 
    hyperparameters = best_hyperparameters[method_name] 
    hyperparameter_string = str(hyperparameters)
    
    model = methods[method_name](model_folder, preprocessing_hash, **hyperparameters, score_function=score_function)
    model_name = model.method_name
    hyperparameter_hash = model.get_hyperparameter_hash()
    hyperparameter_hash_filename = model.get_filename()
    
    base_scores_path = os.path.join(score_folder, which_split)
    base_predictions_path = os.path.join(predictions_folder, which_split)
    scores_path = os.path.join(base_scores_path, model_name, preprocessing_hash, hyperparameter_hash)
    predictions_path = os.path.join(base_predictions_path, model_name, preprocessing_hash, hyperparameter_hash)
    
    y_pred_dfs, _ = load_dataframe_list(predictions_path)
    y_score_dfs, _ = load_dataframe_list(scores_path)
 
    plt.figure()
    plot_predictions(X_dfs_preprocessed, y_pred_dfs, val_file_names, model, pretty_plot=True, n_stations=1)
    plt.savefig(os.path.join(figure_folder, method_name+"_predictions.pdf"), format="pdf")
    plt.savefig(os.path.join(figure_folder, method_name+"_predictions.png"), format="png")