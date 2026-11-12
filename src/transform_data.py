import pandas as pd
import numpy as np
from pathlib import Path
import sqlite3

### Functions

def create_table(df, table_name, primary_keys):
    
    # Map of dtypes from Pandas to SQLite
    dtype_map = {
        'int64': 'INTEGER',
        'Int64': 'INTEGER',
        'float64': 'REAL',
        'object': 'TEXT',
        'datetime64[ns]': 'TIMESTAMP'
    }
    
    sql_query = f"""CREATE TABLE IF NOT EXISTS {table_name} ("""
    
    for col_name, col_type in df.dtypes.items():
        sql_type = dtype_map.get(str(col_type), 'TEXT')
        if col_name not in primary_keys:
            sql_query += f"{col_name} {sql_type}, "
        else:
            sql_query += f"{col_name} {sql_type} NOT NULL, "
    
    sql_query += f"""PRIMARY KEY ({', '.join(primary_keys)}) );"""
    
    return sql_query

#######################################################
    
# Define the base directory for the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load the data
sup_data_file_path = BASE_DIR / 'data' / 'supplier_feed.csv'
supplier_df = pd.read_csv(sup_data_file_path)
supplier_df_new = supplier_df.copy()

### 1. Cleaning 'cost_price' and 'entry_date'

# Remove '$' and convert to float
supplier_df_new['cost_price'] = (
    supplier_df_new['cost_price']
    .str.replace(r'\$', '', regex=True)
    .astype(float)
)

# Convert entry_date to datetime 
supplier_df_new['entry_date'] = pd.to_datetime(supplier_df_new['entry_date'], format='mixed', errors='coerce')
supplier_df_new.dropna(subset=['entry_date'], inplace=True)

### 2. Cleaning and imputing 'stock_level'

# Filter to numeric values only
is_num_mask = supplier_df_new['stock_level'].str.contains(r'^\d+$', na=False, regex=True)
num_stock_df = supplier_df_new[is_num_mask].copy()

# Convert to int and find minimum
num_stock_df['stock_level'] = num_stock_df['stock_level'].astype(int)
minimum_stock = num_stock_df['stock_level'].min()
print('Minimum stock value: ', minimum_stock)

# Standardize entries and map text
supplier_df_new['stock_level'] = supplier_df_new['stock_level'].str.lower().str.strip()
alterations_map = {
    'low': 1,
    'low stock': 1,
    'unavailable': 0,
    'out of stock': 0,
    'nan': np.nan
}
supplier_df_new['stock_level'] = supplier_df_new['stock_level'].replace(alterations_map)

# Convert column to int
supplier_df_new['stock_level'] = pd.to_numeric(
    supplier_df_new['stock_level'],
    errors='coerce'
).astype('Int64')

# Fill missing values with -1 (flag)
supplier_df_new['stock_level'] = supplier_df_new['stock_level'].fillna(-1)

### 3. Imputing 'cost_price'

# Sort the data by 'part_id' and 'entry_date'
supplier_df_new = supplier_df_new.sort_values(['part_id', 'entry_date'])

# Inpute the missing values in 'cost_price' by interpolation
supplier_df_new['cost_price'] = (
    supplier_df_new
    .groupby('part_id')['cost_price']
    .transform(
        lambda x: x.interpolate(
            method='linear',
            limit_direction='both'
        )
    )
)

supplier_df_new['cost_price'] = (
    supplier_df_new['cost_price']
    .fillna(supplier_df_new['cost_price'].median()) #for any remaining nan
)


### 4. Creating new identifier

# Create new column 'stock_entry_id' with a new unique, sequential ID
supplier_df_new.insert(0, 'stock_entry_id', range(len(supplier_df_new)))
supplier_df_new['stock_entry_id'] = supplier_df_new['stock_entry_id'].astype('int64')

# Store the data
output_path = BASE_DIR / 'data' / 'supplier_feed_clean.csv'
supplier_df_new.to_csv(output_path, index=False)

### 5. SQL Database

# Load the metadata file
prod_data_file_path = BASE_DIR / 'data' / 'product_metadata.csv'
product_df = pd.read_csv(prod_data_file_path)

# Create the SQL database, connection and cursor
DB_PATH = BASE_DIR / 'data' / 'auto_parts.db'
connection = sqlite3.connect(DB_PATH)
cursor = connection.cursor()

# Create first table (cleaned supplier transactions)
create_supplier_table = create_table(supplier_df_new, 'cleaned_supplier_data', ['stock_entry_id'])
print(create_supplier_table)
cursor.execute(create_supplier_table)

# Create second table (product metadata)
create_product_table = create_table(product_df, 'product_metadata', ['part_id'])
print(create_product_table)
cursor.execute(create_product_table)

# Clear existing data and insert
cursor.execute("DELETE FROM cleaned_supplier_data;")
supplier_df_new.to_sql(
    name='cleaned_supplier_data',
    con=connection,
    if_exists='append',
    index=False
)

cursor.execute("DELETE FROM product_metadata;")
product_df.to_sql(
    name='product_metadata',
    con=connection,
    if_exists='append',
    index=False
)

# Commit the changes
connection.commit()

# Close the connection
connection.close()