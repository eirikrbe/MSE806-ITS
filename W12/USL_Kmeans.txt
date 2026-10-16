import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans

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
num_cols = ['rho_current', 'packet_delivery_ratio']
X = df[num_cols].values
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# Fit K-Means Model
kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
df['Cluster'] = kmeans.fit_predict(X_scaled)

# Map Clusters to Intuitive Names
cluster_names = {0: 'Free-Flow Traffic', 1: 'Moderate Traffic', 2: 'Severe Bottleneck'}
df['Traffic_State'] = df['Cluster'].map(cluster_names)

# Visual Plot
plt.figure(figsize=(9, 5))
sns.scatterplot(
    data=df, x='rho_current', y='packet_delivery_ratio', 
    hue='Traffic_State', style='road_segment_id', s=120, palette='Set2'
)
plt.title('K-Means Clustering: Identifying Traffic States')
plt.xlabel('Current Vehicle Density (rho_current)')
plt.ylabel('Signal Quality (Packet Delivery Ratio)')
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
plt.tight_layout()
plt.show()