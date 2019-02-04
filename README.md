# The Walking Dead

## Overview

The Walking Dead is an enhancement project for [Apache Airflow](https://airflow.apache.org). The goal is to make Airflow architecture highly available and be able to handle batch processings with minimal downtime. In that case, if any component becomes "dead", it's still "walking".



## An Airflow Application

### Amazon Product Ratings

Before we dig into the project, I want to take one step back. Let's think about what real workflow may use Airflow.



I assume many of us have experiences of online shopping with Amazon.com. Then you must be familiar with this rating section for each product in their website.

![alt text](image/rating%20of%20one%20book.png?raw=true)



Think about how many products in Amazon.com, how many new reviews will be submitted by user everyday. There must be many scheduled batch processings running in their backend for calculating the ratings (stars). I think that's a perfect use case of Airflow in terms of scheduling all these processings.



### Data Pipeline

A straightforward design of such data pipeline would be:



[TODO] - picture of data pipeline



We have multiple pre-defined DAGs, each dag is responsible for calculating average ratings of a certain product category (e.g. Books). Everyday, Airflow scheduler would pick the DAG and run it with current date.



The DAG may contain multiple tasks, but the key one would be submitting a spark job to spark cluster.



Inside that spark job, it will first fetch clients' reviews from S3. Then do some filtering/grouping/aggregating for the real processing. Finally, it will write outputs to a result database.



After the spark processing, you may have an additional tasks for sending notifications or triggering downstream processings.



### Problems!!

As you can see, Airflow plays an important role in this pipeline. Unfortunately, its default setup is fragile.



[TODO] - default setup



- Metastore

  - By default it's using SQLite, which is by design with no horizontal scalability (e.g no multiple connections)

- Worker

  - By default, it's in Sequential Executor mode, which is part of scheduler and can only process one task at one time.

- Scheduler

  - It's single point failure. Simply running multiple scheduler will cause duplications.



### My Solution

My solution is straight forward. Let's go through each component of Airflow and make them highly available.



My work will further be discussed in following sections:



- Highly Available Metastore

  - [Setup Highly Available MySQL](##setup-highly-available-mysql)

  - [Setup Highly Available Load Balancer](##Setup-Highly-Available-Load-Balancer)



- Highly Available Worker

  - [Use Celery Executor Mode](##Use-Celery-Executor-Mode)



- Highly Available Scheduler

  - [Setup Zookeeper](##Setup-Zookeeper)

  - [Scheduler Controller](##Scheduler-Controller)







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



##Setup Highly Available Load Balancer

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



`priority 100` is the default priority for this instance. Whenever a check fails, we will decrease this score by 2 based on `faill 2`. Among all the Keepalived peers, whichever has the highest priority will become master.



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

