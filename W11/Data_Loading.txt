import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline

# 1. Load Sheet2 dataset
df = pd.read_excel('Generate_Dataset.xlsx', sheet_name='Sheet2')
df.columns = [
    'time_step', 'road_segment_id', 'rho_current', 'rho_past', 
    'rho_estimated', 'active_event', 'packet_delivery_ratio', 
    'recommended_route', 'trip_time_minutes'
]
df['active_event'] = df['active_event'].fillna('None')

# 2. Define Features and Targets
feature_cols = ['time_step', 'road_segment_id', 'rho_current', 'rho_past', 'rho_estimated', 'active_event', 'trip_time_minutes']
X = df[feature_cols]

# Classification Target (Binary: Route_1 = 0, Route_2 = 1)
y_class = (df['recommended_route'] == 'Route_2').astype(int)

# Regression Target (Continuous PDR)
y_reg = df['packet_delivery_ratio']

# 3. Create Feature Preprocessor
preprocessor = ColumnTransformer(
    transformers=[
        ('num', StandardScaler(), ['time_step', 'rho_current', 'rho_past', 'rho_estimated', 'trip_time_minutes']),
        ('cat', OneHotEncoder(drop='first', handle_unknown='ignore'), ['road_segment_id', 'active_event'])
    ]
)

print("Setup complete! Total rows loaded:", len(df))