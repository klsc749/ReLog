ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

MAINTAINER ngocpq <phungquangngoc@gmail.com>

#############################################################################
# Requirements
#############################################################################

RUN \
  apt-get update -y && \
  apt-get install software-properties-common -y && \
  apt-get update -y && \
  apt-get install -y openjdk-11-jdk \
                git \
                build-essential \
                subversion \
                perl \
                curl \
                unzip \
                cpanminus \
                make \
                && \
  rm -rf /var/lib/apt/lists/*

RUN git config --global core.hardlinks false

# Java version
ENV JAVA_HOME /usr/lib/jvm/java-11-openjdk-amd64

# Timezone
ENV TZ=America/Los_Angeles
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone


#############################################################################
# Setup Defects4J
#############################################################################

# ----------- Step 1. Copy vendored defects4j -------------------
COPY defects4j /defects4j

# ----------- Step 2. Initialize Defects4J ---------------------
WORKDIR /defects4j
RUN cpanm --from https://cpan.metacpan.org --installdeps .
RUN ./init.sh

# ----------- Step 3. Add Defects4J's executables to PATH: ------
ENV PATH="/defects4j/framework/bin:${PATH}"  
#--------------
