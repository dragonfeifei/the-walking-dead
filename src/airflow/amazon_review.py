import datetime as dt

from airflow import DAG
from airflow.operators.bash_operator import BashOperator
from airflow.operators.python_operator import PythonOperator


def print_message():
    print('Job finished!')


default_args = {
    'owner': 'me',
    'start_date': dt.datetime(2019, 01, 01),
    'retries': 2,
    'retry_delay': dt.timedelta(minutes=1),
}


with DAG('amazon_review',
         default_args=default_args,
         schedule_interval=None,
         ) as dag:

    calc_review = BashOperator(task_id='calc_review',
                               bash_command='spark-submit ~/workspace/the-walking-dead/src/spark/calculate.py -d {{ execution_date.strftime("%Y%m%d") }} -c Luggage')
    notify = BashOperator(task_id='notify',
                          bash_command='sleep 20')
    trigger = PythonOperator(task_id='trigger',
                             python_callable=print_message)


calc_review >> notify >> trigger
