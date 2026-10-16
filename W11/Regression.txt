from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score

# 1. Build and Train Linear Regression Model
linreg_pipeline = Pipeline([
    ('prep', preprocessor), 
    ('reg', LinearRegression())
])
linreg_pipeline.fit(X, y_reg)

# 2. Generate Predictions
df['LinReg_Predicted_PDR'] = linreg_pipeline.predict(X)

# 3. Print Performance
rmse = np.sqrt(mean_squared_error(y_reg, df['LinReg_Predicted_PDR']))
r2 = r2_score(y_reg, df['LinReg_Predicted_PDR'])
print(f"Linear Regression RMSE: {rmse:.5f} | R2 Score: {r2:.5f}")

# 4. Save Regression CSV
df[['time_step', 'road_segment_id', 'packet_delivery_ratio', 'LinReg_Predicted_PDR']].to_csv('2_Regression_LinReg.csv', index=False)
print("Exported: '2_Regression_LinReg.csv'")