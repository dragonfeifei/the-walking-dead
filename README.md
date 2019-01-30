# the-walking-dead

## Project Idea:
  Updating Amazon review rating with fault-tolerant Apache Airflow

## Tech Stack:
- Apache Airflow - scheduling
- Apache Spark - querying and calculation
- MySQL - highly available database for Airflow metadata store

## Data Source:
Amazon Customer Reviews Dataset (S3)
130+ million customer reviews

## Engineering Challenge:
Setup MySQL in replication mode, leverage airflow-scheduler-failover-controller and Load balancer to achieve highly availability. Use MySQL as external database for Airflow.

## Business Value:
With this highly-available batch processing architecture, we can process large volume jobs without downtime.

## MVP:
1. have a DAG for pulling data from s3 and use spark operator to caculate average rating for a specific product
2. configure Airflow to connect to highly available MySQL
	
## Stretch Goals:
make scheduler highly available as well
