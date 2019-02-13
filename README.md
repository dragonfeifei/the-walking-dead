# The Walking Dead

## Overview

The Walking Dead is an enhancement project for [Apache Airflow](https://airflow.apache.org). The goal is to make Airflow architecture highly available and be able to handle batch processings with minimal downtime. In that case, if any component becomes "dead", it's still "walking".



## Example Airflow Application

### Amazon Product Ratings

Before we dig into the project, I want to take one step back. Let's think about what real workflow may use Airflow.



I assume many of us have experiences of online shopping with Amazon.com. Then you must be familiar with this rating section for each product in their website.

![alt text](image/rating%20of%20one%20book.png?raw=true)



Think about how many products in Amazon.com, how many new reviews will be submitted by user everyday. There must be many scheduled batch processings running in their backend for calculating the ratings (stars). I think that's a perfect use case of Airflow in terms of scheduling all these processings.



### Data Pipeline

A straightforward design of such data pipeline would be:


![alt text](image/data%20pipeline.png?raw=true)


We have multiple pre-defined DAGs, each dag is responsible for calculating average ratings of a certain product category (e.g. Books). Everyday, Airflow scheduler would pick the DAG and run it with current date.



The DAG may contain multiple tasks, but the key one would be submitting a spark job to spark cluster.



Inside that spark job, it will first fetch clients' reviews from S3. Then do some filtering/grouping/aggregating for the real processing. Finally, it will write outputs to a result database.



After the spark processing, you may have an additional tasks for sending notifications or triggering downstream processings.



### Problems!!

As you can see, Airflow plays an important role in this pipeline. Unfortunately, its default setup is fragile.

![alt text](image/default%20setup.png?raw=true)

- Scheduler

  - It's a single point failure. Simply running multiple scheduler will cause duplications.

- Worker

  - By default, it's in Sequential Executor mode, which is part of scheduler and can only process one task at one time.

- Metastore

  - By default it's using SQLite, which is by design with no horizontal scalability (e.g no multiple connections).



### My Solution

My solution is straight forward. Let's go through each component of Airflow and make them highly available.



My work will further be discussed in following sections:

- Highly Available Scheduler

  - [Implement Scheduler Controller](#implement-scheduler-controller)

- Highly Available Worker

  - [Use Celery Executor Mode](#use-celery-executor-mode)

- Highly Available Metastore

  - [Setup Highly Available MySQL](#setup-highly-available-mysql)

  - [Setup Highly Available Load Balancer](#setup-highly-available-load-balancer)


You can see a **Live Demo** [here](http://bit.ly/thewalkingdeadairflowvideo):

Final enhanced architecture will look like:

![alt text](image/final%20architecture.png?raw=true)


## Implement Scheduler Controller

### 1. Introduction
> The Airflow scheduler monitors all tasks and all DAGs, and triggers the task instances whose dependencies have been met. Behind the scenes, it spins up a subprocess, which monitors and stays in sync with a folder for all DAG objects it may contain, and periodically (every minute or so) collects DAG parsing results and inspects active tasks to see whether they can be triggered.

From the official document, we can see scheduler is designed to run as a single persistent service (daemon) in an stable environment. No parallelism is considered.

This design is clean. However it implies a single point failure: we need to make sure there always is one, and only one scheduler running at any given point of time.

### 2. Technical Decisions

#### Controller
In order to solve the previous mentioned issue, I created a new component called **scheduler controller** as new member of Airflow. 

This controller is supposed to run as daemon on multiple nodes. All daemons will be coordinated and only one of them will be elected as master. Once elected, master will bring up one scheduler (as subprocess) on the same node and keep monitor it.

In scenario such as scheduler crashes: 

- The controller will withdraw its leadership and quit. A new round of election will be then triggered. New master will start a scheduler as replacement.

In scenario such as controller crashes or current node completely goes down:

- Master will stop sending heartbeats. After certain timeout, other controllers will treat it as dead and start new election.

#### Coordinator
How to handle leader election and heartbeats between all controller could be difficult, especially when you require highly availability. Luckily, we have [Apache Zookeeper](https://zookeeper.apache.org) designed for such use case. By using its python api [Kazoo](https://kazoo.readthedocs.io/en/latest/), we can easily integrate the **election** receipt with our controller.

### 3. Steps
#### Bring up instances

We need to bring up total 6 machines for our Airflow and Zookeeper services. Two of them will be used for running Airflow components. The rest four will used for running Zookeeper.

Note:
>  It's recommanded to use **odd** number of nodes for Zookeeper inorder to achieve consensus effectively. Due to the limited EC2 resources, I also need to host Spark on the same cluster. For simplicity, let's just stick with 4 instances.

Let's first bring up two EC2 instances using [pegasus](https://github.com/InsightDataScience/pegasus) for Airflow.

```
$ peg up deployment/airflow-1.yml
$ peg up deployment/airflow-2.yml
```

Then four for Zookeeper & Spark.

```
$ peg up deployment/spark-master.yml
$ peg up deployment/spark-workers.yml
```

#### Install Zookeeper & Spark

pegasus provides convient interface for installing them

```
$ peg install [spark-cluster] spark
$ peg install [spark-cluster] zookeeper
```

and start them.

```
$ peg service [spark-cluster] spark start
$ peg service [spark-cluster] zookeeper start
```

By default, Zookeeper service can be connected on port 2181.

#### Install Airflow
Before installing, we can set up the default airflow home address:

```
$ export AIRFLOW_HOME=~/airflow
```

Then we can install airflow and its packages using pip:

```
$ sudo pip install airflow[async,devel,celery,crypto,druid,gcp_api,jdbc,hdfs,hive,kerberos,ldap,password,mysql,qds,rabbitmq,s3,samba,slack]
```

Make sure `celery`, `rabbitmq` and `mysql` plug-ins are included. We gonna need them to make other parts of Airflow to be highly available.

An `airflow.cfg` file is generated in the airflow home directory. If you can't find it, run

```
$ airflow initdb
```
to create it.

A lot of fields need to be modified in this cfg file, but we can skip it for now. We will revisit it in [Use Celery Executor Mode](#use-celery-executor-mode) and [Setup Highly Available Load Balancer](#setup-highly-available-load-balancer).

Be sure to copy our DAG into Airflow's dag folder, so scheduler will be aware of our pipeline (recap: [Example Airflow Application](#example-airflow-application)):

```
$ cp src/airflow/amazon_review.py ~/airflow/dags
```


#### Start Scheduler Controller

We will then start our controller on both Airflow machines. Simply run:

```
$ python src/airflow/scheduler_controller.py
```

> You may want to change its content a little bit to reflect your Zookeeper connection. 

On one of the machine, you should see a hello page from Airflow, which means it become the master controller and successfully started scheduler.

On the other one, you can see it's waiting to become master.

And that's it, we have made scheduler highly available!

## Use Celery Executor Mode

### 1. Introduction
Now let's think about how to make executions (workers) highly available and efficient.

The actual execution of the task happens separately from the scheduler process. There are at least 3 strategies included in Airflow: sequential, local, Celery executor.

- Sequential Executor
  - This is the default and is part of scheduler logic. You can only run one task at one time.

- Local Executor
  - Instead of running inside scheduler, in this mode, scheduler will spawn mulitiple subprocesses. We can execute tasks in parallel but only within a single machine.

- Celery Executor
  - In order to scale it further, we need a little help from [Celery](http://docs.celeryproject.org/en/latest/). All the tasks which are ready to run will be pushed into a distributed queue by scheduler. Then individual workers can be run on multiple machines and pick up tasks by querying the queue. Celery uses [RabbitMQ](https://www.rabbitmq.com) as recommended broker.


### 2. Technical Decisions
I picked Celery Executor. It's the recommended way of running Airflow in production environment. RabbitMQ can easily be tuned as highly available too. We can run workers on as many as machines you want. And they are independent, we can still process jobs even though some of the workers are not available.

### 3. Steps
#### Install RabbitMQ

Considering the time of the project, I didn't actually setup RabbitMQ in a [highly available way](https://www.rabbitmq.com/ha.html). Instead, I just started it on one of the Airflow machines. 

```
$ sudo apt-get install rabbitmq-server

$ sudo service rabbitmq-server start

```

#### Change Airflow Configurations

Let's modify `airflow.cfg` to integrate with Celery and RabbitMQ.

```
[core]
# Replace default SequentialExecutor with CeleryExecutor
executor = CeleryExecutor

[celery]
# Tell Celery to use RabbitMQ as broker
broker_url = amqp://guest:guest@localhost:5672//

# Tell workers where is our metastore
result_backend = db+mysql://airflow:airflow@52.11.179.216:3306/airflow

```

And flush all the changes:

```
$ airflow initdb
```

By now, scheduler will start pushing tasks to RabbitMQ. Then we can start workers to pick them up:

```
$ airflow worker
```

## Setup Highly Available MySQL

### 1. Introduction

MySQL is a popular open source relational database used by many companys including Google, Facebook and Twitter. It is quite stable and easy to use. I picked it as the external database for storing metadata of Airflow. Those metadata help Airflow maintain the statuses of executed jobs. Losing access to such data will directly impact Airflow and cause failure or duplication. Thus making MySQL highly available is critical to our application. Here I am going to show you how I did it.

### 2. Technical Decisions

#### Solutions

There are two primary solutions to make MySQL highly available:



1. MySQL Replication

1. MySQL Cluster (NDB Cluster)



Following picture clearly demonstrates the tradeoff between them:

![alt text](https://dev.mysql.com/doc/mysql-ha-scalability/en/images/ha-cost-vs-nines.png)

Detailed comparison can also be found [here](https://dev.mysql.com/doc/mysql-ha-scalability/en/ha-overview.html).



Since our application is mainly for calculating daily average ratings of amazon products, having a max downtime about one day is generally acceptable. During the downtime, customers may not see most accurate ratings but for most products, their ratings would be fairly stable across days. As a result, using replication mode is good enough in our use case.



#### Topologies



MySQL Replication mode enables data from one server (aka master) to be copied to one or more other servers (aka slaves). The replication is done in an async way so that you may experience lag between master and each slave.



The topology I chose is Master-Master as demonstrated with below graph.



![alt text](https://severalnines.com/sites/default/files/resources/tutorials/mysql-replication-tutorial/image13.png)



Both servers can receive writes/reads. Writes will be replicated to the peer so they have same set of data.



One disadvantage you need to know is: such replication will not handle conflicts (when two requests are updating the same record with different values at the same time). So as a common practice, we only write to one of them. The other one works as hot backup. We achieve this by setting load balancer's routing rule.



Multiple advantages come from this topology:



1. No additional controller is needed to perform leader election and promote slave to be new master

1. It improves the scalability by accepting writes on both servers as long as there is no conflict



### 3. Steps

#### Bring up instances

We bring up two EC2 instances using [pegasus](https://github.com/InsightDataScience/pegasus).



```
$ peg up deployment/mysql-1.yml
$ peg up deployment/mysql-2.yml
```

#### Install MySQL

It is available in apt repository.



```
$ sudo apt-get install mysql-server mysql-client
```

#### Change Configuration

Config file is located at `/etc/mysql/mysql.conf.d/mysqld.cnf`

Several things need to be changed under `[mysqld]`section.



Server 1 (Real Master):



```
# unique id for each server
server-id = 1 

# enabled for slave, to make sure we can append the log copied from
#  master to its own log
log_slave_updates = 1

# for use with master-to-master replication, and can be used to 
#  control the operation of AUTO_INCREMENT columns
auto-increment-increment = 2
auto-increment-offset = 1

# airflow requires it to be on
explicit_defaults_for_timestamp = 1
```



Server 2 (Hot Backup):



```
# unique id for each server
server-id = 2 

# enabled for slave, to make sure we can append the log copied from
#  master to its own log
log_slave_updates = 1

# for use with master-to-master replication, and can be used to 
#  control the operation of AUTO_INCREMENT columns
auto-increment-increment = 2
auto-increment-offset = 2



# airflow requires it to be on
explicit_defaults_for_timestamp = 1
```

Restart mysql to pickup configuration changes



```
$ sudo service mysql restart
```



#### Create Replication Users

Log into mysql and enter following commands for each server (replace the IP with your master's)



```
$ sudo mysql

mysql> GRANT REPLICATION SLAVE ON *.* TO 'replicauser'@'10.0.0.5' IDENTIFIED BY 'somestrongpassword';
```



#### Configure Database Replication

On server 1:



```
mysql> SHOW MASTER STATUS;
+------------------+----------+--------------+------------------+
| File             | Position | Binlog_Do_DB | Binlog_Ignore_DB |
+------------------+----------+--------------+------------------+
| mysql-bin.000001 |      277 |              |                  |
+------------------+----------+--------------+------------------+
```



On server 2:



```
mysql> STOP SLAVE;

mysql> CHANGE MASTER TO master_host='10.0.0.8',
master_port=3306, master_user='replicauser',
master_password='somestrongpassword', master_log_file='mysql-bin.000001',
master_log_pos=531;

mysql> START SLAVE;
```



Then do the similar thing respectively on the other master-slave direction.



By now, we should have successfully configured a highly available MySQL replication cluster.



## Setup Highly Available Load Balancer

### 1. Introduction

Now we have two MySQL servers ready to accept queries, but Airflow only needs to talk to one of them. Also, as we mentioned in the MySQL setup session, due to our Master-Master topology, in order to avoid conflicts, we prefer traffic only goes to a single node.





### 2. Technical Decisions

#### Architecture

My first solution would be having a load balancer above database level. It could provide a single interface to clients and have the ability to re-direct traffic when one server goes down.



However, we are introducing a single point failure here. What if the load balancer itself goes down? Then no one can connect to our databases. To make load balancer highly available too, I decided to setup a backup one. The final architecture is showed in below graph:



![alt text](image/Load%20Balancer.png?raw=true)



An elastic IP is originally associated to the master load balancer. Clients like Airflow will only talk to this IP. Master load balancer then forwards requests to the preferred MySQL server. If that server crashed, it will re-direct traffic to the backup server.



There will be a instance of Keepalived (tiny but powerful tool for handling check and failovers) co-located with each load balancer. It's responsible for checking the status of local load balancer and communicating with its peer. Whenever it detects that the local one is not functioning. It's peer on the other machine will "steal" the IP. As a result, the backup load balancer now serves.



#### ELB or HAproxy

AWS’s Elastic Load Balancer (ELB) offers customers an easy way to handle load balancing for applications hosted on multiple Amazon EC2 instances. It manages the availability and failover for you. However, obviously, it's not free.



Come to open source solutions, I eventually picked HAProxy for these reasons:



1. Comprehensive stats with a nice UI

1. Easy to setup with many routing algorithms available





### 3. Steps

#### Bring up instances

We need two instances.



```
$ peg up deployment/lb-1.yml
$ peg up deployment/lb-2.yml
```

#### Install HAProxy



```
$ sudo apt-get install haproxy
```



And change the config on `/etc/haproxy/haproxy.cfg`



```
global
    chroot      /var/lib/haproxy
    pidfile     /var/run/haproxy.pid
    maxconn     4000
    user haproxy
    group haproxy
defaults
    mode http
    log global
    retries 2
    timeout connect 5s
    timeout server 480m
    timeout client 480m
listen stats
    bind *:9999
    stats enable
    stats hide-version
    stats uri /stats
    stats auth statadmin:statadminpass
listen mysql-cluster
    bind *:3306
    mode tcp
    option mysql-check user haproxy_check
    balance source
    server mysql-1 10.0.0.8:3306 check
    server mysql-2 10.0.0.5:3306 check
```



and start it



```
$ sudo service haproxy start
```

We make it listen to port 3306 and route traffic to one of the listed servers with check enabled. The balancing algorithm is `source`, which will try to send to same server as long as the traffic is from the same source.



You can see we also start a webserver displaying stats on port 9999.



![alt text](image/HAProxy%20Stats.png?raw=true)



#### Install Keepalived



```
$ sudo apt-get install keepalived
```



And change the config on `/etc/keepalived/keepalived.conf`



```
vrrp_script check_haproxy {
    script "pidof haproxy"
    interval 5
    fall 2
    rise 2
}

vrrp_instance VI_1 {
    debug 2
    interface eth0
    state MASTER
    virtual_router_id 1
    priority 110
    unicast_src_ip 10.0.0.9

    unicast_peer {
    	10.0.0.10
    }

    track_script {
        check_haproxy
    }

    notify_master /etc/keepalived/failover.sh root
}
```

We use cmd line `pidof haproxy` to check whether the local load balancer is running. Keepalived will run it periodically.



`priority 110` is the default priority for this instance. Whenever a check fails, we will decrease this score by 2 based on `faill 2`. Among all the Keepalived peers, whichever has the highest priority will become master.



`notify_master` is pointed to a script and will run it when this Keepalived instance becomes master (e.g. the HAProxy on the other machine is down).



Inside `failover.sh`, we are going to disassociate elastic IP from existing machine, and associate to current machine.



```
aws ec2 disassociate-address --public-ip $EIP
aws ec2 associate-address --public-ip $EIP --instance-id $INSTANCE_ID
```



and finally, we start Keepalived on each machine



```
$ sudo service keepalived start
```



We can test the failover by running following command on master



```
$ sudo service haproxy stop
```

and check the AWS console to see the elastic IP got transferred.

#### Integrate with Airflow
We will specify the Elastic IP in `airflow.cfg` to let Airflow use our highly available metastore.

```
[core]
# Tell scheduler where is our metastore
sql_alchemy_conn = mysql://airflow:airflow@52.11.179.216:3306/airflow

[celery]
# Tell workers where is our metastore
result_backend = db+mysql://airflow:airflow@52.11.179.216:3306/airflow
```

And flush all the changes:

```
$ airflow initdb
```

## Summary
To sum up, I made several enhancement and setups to make Airflow architecture highly available:

- Implemented a scheduler controller to maintain scheduler status
- Configured worker to be run in distributed mode
- Setup external metastore with load balancing

As an example, an **Amazon Ratings Calculation** pipeline is implemented with this new architecture. By showing the pipeline is never stopped while bringing down components, we demonstrate that our workflow is highly available. The dead is still walking!
