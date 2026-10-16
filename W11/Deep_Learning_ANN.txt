from sklearn.neural_network import MLPClassifier, MLPRegressor

# 1. Deep Learning Classification Head
ann_clf_pipeline = Pipeline([
    ('prep', preprocessor), 
    ('ann_clf', MLPClassifier(hidden_layer_sizes=(32, 16), activation='relu', max_iter=1000, random_state=42))
])
ann_clf_pipeline.fit(X, y_class)
df['ANN_Predicted_Route_Code'] = ann_clf_pipeline.predict(X)
df['ANN_Predicted_Route'] = df['ANN_Predicted_Route_Code'].map({0: 'Route_1', 1: 'Route_2'})

# 2. Deep Learning Regression Head
ann_reg_pipeline = Pipeline([
    ('prep', preprocessor), 
    ('ann_reg', MLPRegressor(hidden_layer_sizes=(32, 16), activation='relu', max_iter=1000, random_state=42))
])
ann_reg_pipeline.fit(X, y_reg)
df['ANN_Predicted_PDR'] = ann_reg_pipeline.predict(X)

# 3. Save Deep Learning and Master CSV Files
df[['time_step', 'road_segment_id', 'recommended_route', 'ANN_Predicted_Route', 'packet_delivery_ratio', 'ANN_Predicted_PDR']].to_csv('3_DeepLearning_ANN.csv', index=False)
df.to_csv('Master_Sheet2_ML_Predictions.csv', index=False)

print("Exported: '3_DeepLearning_ANN.csv' & 'Master_Sheet2_ML_Predictions.csv'")