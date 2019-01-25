import datetime as dt

from airflow import DAG
from airflow.operators.bash_operator import BashOperator
from airflow.operators.python_operator import PythonOperator


def print_world():
    print('world')


default_args = {
    'owner': 'me',
    'start_date': dt.datetime(2019, 01, 21),
    'retries': 1,
    'retry_delay': dt.timedelta(minutes=5),
}


with DAG('amazon_review',
         default_args=default_args,
         schedule_interval='*/10 * * * *',
         ) as dag:

    print_hello = BashOperator(task_id='calc_review',
                               bash_command='spark-submit ~/workspace/the-walking-dead/src/spark/calculate.py -d 20190101 -c Luggage')
    sleep = BashOperator(task_id='sleep',
                         bash_command='sleep 1')
    print_world = PythonOperator(task_id='print_world',
                                 python_callable=print_world)


print_hello >> sleep >> print_world
