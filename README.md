# Yelp Health Data Curation - An AWS-based data pipeline to extract, process, store, and monitor Yelp "health-related" facility data
 * **Description**: The first, foundational component of the Center for Healthcare Transformation and Innovation (CHTI) AWS data infrastructure, meant to automate novel dataset creation and manage access to high-value data assets for use in academic and operations research. The essential functions of the *Yelp health data pipeline* are as follows:
   * Launch a preconfigured, CHTI-owned EC2 instance optimized for data collection and processing via launch template and execute the *yelp_health_pipeline.py* script
   * extract Yelp-provided zipfiles of daily database snapshots for all Yelp "health-related" facilities from a Yelp-owned S3 bucket
   * unzip each zip file and process the corresponding JSON file into three master csv files for facilities, facility categories, and facility reviews
   * save zip files, JSON files, and processed master files in corresponding CHTI-owned S3 buckets with appropriate storage classes to minimize costs
   * create user groups and roles with appropriate permissions to streamline data access requests and ensure data integrity/consistency in support of ongoing health system initiatives.
 * **Role**: *Lead Data Scientist* allocated to the CHTI AWS data infrastructure
