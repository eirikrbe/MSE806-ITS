from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

# 1. Build and Train Logistic Regression Model
logreg_pipeline = Pipeline([
    ('prep', preprocessor), 
    ('clf', LogisticRegression(random_state=42))
])
logreg_pipeline.fit(X, y_class)

# 2. Generate Predictions
df['LogReg_Predicted_Code'] = logreg_pipeline.predict(X)
df['LogReg_Predicted_Route'] = df['LogReg_Predicted_Code'].map({0: 'Route_1', 1: 'Route_2'})

# 3. Print Performance
acc = accuracy_score(y_class, df['LogReg_Predicted_Code'])
print(f"Classification Training Accuracy: {acc * 100:.2f}%")

# 4. Save Classification CSV
df[['time_step', 'road_segment_id', 'recommended_route', 'LogReg_Predicted_Route']].to_csv('1_Classification_LogReg.csv', index=False)
print("Exported: '1_Classification_LogReg.csv'")