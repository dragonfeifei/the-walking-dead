import datetime as dt
from airflow import DAG
from airflow.operators.bash_operator import BashOperator
from airflow.operators.python_operator import PythonOperator

# Dummy function for triggering downstream processing
def trigger_downstream():
    print('triggered!')

default_args = {
    'owner': 'me',
    'start_date': dt.datetime(2019, 01, 01),
    'retries': 2,
    'retry_delay': dt.timedelta(minutes=1),
    'depends_on_past': False,
}

with DAG(
    'amazon_review',
    default_args=default_args,
    schedule_interval='@daily'
) as dag:

    # Submit spark job using commandline
    # Alternative: use SparkSubmitOperator
    calc_review = BashOperator(
        task_id='calc_review',
        bash_command=(
            'spark-submit '
            '~/workspace/the-walking-dead/src/spark/calculate.py '
            '-d {{ execution_date.strftime("%Y%m%d") }} -c Luggage'
        )
    )

    # Send notifications
    # Dummy: Just sleep now, ideally we should call certain apis
    notify = BashOperator(
        task_id='notify',
        bash_command='sleep 20'
    )

    # Trigger downstreams
    trigger = PythonOperator(
        task_id='trigger',
        python_callable=trigger_downstream
    )

# Dependency
calc_review >> notify >> trigger
