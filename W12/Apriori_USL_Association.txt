import pandas as pd
from mlxtend.frequent_patterns import apriori, association_rules

# Load Dataset
file_path = 'Generate_Dataset.xlsx'
df = pd.read_excel(file_path, sheet_name='Sheet2')
df.columns = [
    'time_step', 'road_segment_id', 'rho_current', 'rho_past', 
    'rho_estimated', 'active_event', 'packet_delivery_ratio', 
    'recommended_route', 'trip_time_minutes'
]
df['active_event'] = df['active_event'].fillna('None')

# Discretize Features into True/False Conditions
df_assoc = pd.DataFrame()
df_assoc['High_Traffic_Density'] = df['rho_current'] > 170
df_assoc['Signal_Degraded'] = df['packet_delivery_ratio'] < 0.73
df_assoc['Accident_Present'] = df['active_event'] == 'Accident'

# Apply Apriori Algorithm
frequent_itemsets = apriori(df_assoc, min_support=0.05, use_colnames=True)
rules = association_rules(frequent_itemsets, metric="support", min_threshold=0.05)

# Print Discovered Rules
print("=== DISCOVERED TRAFFIC ASSOCIATION RULES ===")
for idx, row in rules.iterrows():
    antecedent = list(row['antecedents'])[0]
    consequent = list(row['consequents'])[0]
    print(f"Rule {idx+1}: IF [{antecedent}] ==> THEN [{consequent}]")