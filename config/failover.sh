#!/bin/bash

export AWS_ACCESS_KEY_ID=
export AWS_SECRET_ACCESS_KEY=
export AWS_DEFAULT_REGION=us-west-2

EIP=52.11.179.216
INSTANCE_ID=i-0b218126691d51c45
#ALLOCATION_ID=eipalloc-09d91b2cea59cec54
#SECOND_IP=10.0.0.13

aws ec2 disassociate-address --public-ip $EIP
aws ec2 associate-address --public-ip $EIP --instance-id $INSTANCE_ID

