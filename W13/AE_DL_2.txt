import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.preprocessing import StandardScaler
import tensorflow as tf
from tensorflow.keras import layers, models

# 1. Load Excel file and target Sheet2 explicitly
file_path = 'Generate_Dataset.xlsx'
excel_file = pd.ExcelFile(file_path)

target_sheet = 'Sheet2' if 'Sheet2' in excel_file.sheet_names else excel_file.sheet_names[0]
df = pd.read_excel(file_path, sheet_name=target_sheet)
df.columns = df.columns.str.strip()

# 2. Extract features using exact column matching
feature_keywords = ['rho_current', 'rho_past', 'rho_estimate', 'packet_deliv', 'trip_time']
selected_features = []

for kw in feature_keywords:
    matched = [c for c in df.columns if kw.lower() in c.lower()]
    if matched:
        selected_features.append(matched[0])

print(f"Loaded Sheet: '{target_sheet}'")
print(f"Mapped {len(selected_features)}/5 Feature Columns:", selected_features)

# 3. Extract numerical telemetry matrix
X = df[selected_features].values

# 4. Standardize features
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# 5. Build Deep Autoencoder Architecture (5 -> 16 -> 2 -> 16 -> 5)
input_dim = X_scaled.shape[1]

model = models.Sequential([
    layers.Input(shape=(input_dim,)),
    layers.Dense(16, activation='relu'),
    layers.Dense(2, activation='relu'),
    layers.Dense(16, activation='relu'),
    layers.Dense(input_dim, activation='linear')
])

model.compile(optimizer='adam', loss='mse')

# 6. Train Model & Save History
history = model.fit(X_scaled, X_scaled, epochs=50, batch_size=8, verbose=0)

# 7. Calculate Reconstruction Error (MSE) without TF retracing warnings
reconstructions = model(X_scaled, training=False).numpy()
mse_errors = np.mean(np.square(X_scaled - reconstructions), axis=1)
df['Reconstruction_Error'] = mse_errors

# Set Statistical Threshold (Mean + 2 * Std)
threshold = df['Reconstruction_Error'].mean() + 2 * df['Reconstruction_Error'].std()

# ==========================================
# GRAPH 1: Model Training Loss Curve
# ==========================================
plt.figure(figsize=(8, 4))
plt.plot(history.history['loss'], color='#2b5c8f', linewidth=2, label='Training Loss (MSE)')
plt.title('Graph 1: Deep Autoencoder Training Loss', fontsize=13, fontweight='bold')
plt.xlabel('Epochs', fontsize=11)
plt.ylabel('Loss (MSE)', fontsize=11)
plt.grid(True, linestyle='--', alpha=0.5)
plt.legend()
plt.tight_layout()
plt.show()

# ==========================================
# GRAPH 2: Operational Anomaly Dashboard
# ==========================================
sns.set_theme(style='whitegrid')
plt.figure(figsize=(10, 5))

# Identify metadata columns dynamically
time_col = [c for c in df.columns if 'time_step' in c.lower()][0]
segment_col = [c for c in df.columns if 'road_segment' in c.lower()][0]

sns.lineplot(
    data=df,
    x=time_col,
    y='Reconstruction_Error',
    hue=segment_col,
    marker='o',
    linewidth=2
)

plt.axhline(
    y=threshold, 
    color='red', 
    linestyle='--', 
    linewidth=2, 
    label=f'Anomaly Alert Threshold ({round(threshold, 2)})'
)

plt.title('Graph 2: Deep Autoencoder Anomaly Spikes', fontsize=13, fontweight='bold')
plt.xlabel('Simulation Time Step (Minutes)', fontsize=11)
plt.ylabel('Reconstruction Error (MSE)', fontsize=11)
plt.legend(bbox_to_anchor=(1.02, 1), loc='upper left')
plt.tight_layout()
plt.show()