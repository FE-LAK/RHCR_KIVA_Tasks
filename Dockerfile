FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    build-essential \
    cmake \
    ninja-build \
    pkg-config \
    libboost-all-dev \
    python3 \
    python3-pip \
    python3-matplotlib \
    python3-numpy \    
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work

CMD ["/bin/bash"]