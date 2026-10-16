import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

# Set plot style
sns.set_theme(style="whitegrid")

# Load Dataset
file_path = 'Generate_Dataset.xlsx'
df = pd.read_excel(file_path, sheet_name='Sheet2')
df.columns = [
    'time_step', 'road_segment_id', 'rho_current', 'rho_past', 
    'rho_estimated', 'active_event', 'packet_delivery_ratio', 
    'recommended_route', 'trip_time_minutes'
]

# Select and Scale Features
num_cols = ['rho_current', 'rho_past', 'rho_estimated', 'packet_delivery_ratio', 'trip_time_minutes']
X = df[num_cols].values
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# Fit PCA (2 Components)
pca = PCA(n_components=2)
X_pca = pca.fit_transform(X_scaled)

df['PC1'] = X_pca[:, 0]
df['PC2'] = X_pca[:, 1]

# Visual Plot
plt.figure(figsize=(9, 5))
sns.scatterplot(
    data=df, x='PC1', y='PC2', 
    hue='road_segment_id', s=130, palette='tab10'
)
plt.title('PCA: 2D Feature Compression Map')
plt.xlabel(f'Principal Component 1 ({pca.explained_variance_ratio_[0]*100:.1f}% Variance)')
plt.ylabel(f'Principal Component 2 ({pca.explained_variance_ratio_[1]*100:.1f}% Variance)')
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
plt.tight_layout()
plt.show()