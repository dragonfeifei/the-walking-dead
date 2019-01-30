#!/bin/bash

export AWS_ACCESS_KEY_ID=
export AWS_SECRET_ACCESS_KEY=
export AWS_DEFAULT_REGION=us-west-2

aws configure list >> /home/ubuntu/abc.log 2>&1

EIP=52.11.179.216
INSTANCE_ID=i-0b218126691d51c45
ALLOCATION_ID=eipalloc-09d91b2cea59cec54
SECOND_IP=10.0.0.13

aws ec2 disassociate-address --public-ip $EIP >> /home/ubuntu/abc.log 2>&1
#aws ec2 associate-address --public-ip $EIP --instance-id $INSTANCE_ID
aws ec2 associate-address --allocation-id $ALLOCATION_ID --instance-id $INSTANCE_ID --private-ip-address $SECOND_IP >> /home/ubuntu/abc.log 2>&1

