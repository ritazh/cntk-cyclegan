FROM microsoft/cntk
RUN apt-get update
RUN apt-get install -y python3-tk
RUN apt-get install -y python-pip
RUN apt-get build-dep -y python-matplotlib
WORKDIR /app
COPY ./requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

RUN wget https://www.open-mpi.org/software/ompi/v1.10/downloads/openmpi-1.10.3.tar.gz && \
    tar -xzvf ./openmpi-1.10.3.tar.gz && \
	cd openmpi-1.10.3 && \
    ./configure --prefix=/usr/local/mpi && \
    make -j all	&& \
    sudo make install && \
    echo "LD_LIBRARY_PATH='$LD_LIBRARY_PATH:/usr/local/mpi/lib:/usr/lib/x86_64-linux-gnu_custom'" >> ~/.profile && \
    echo "LD_LIBRARY_PATH='$LD_LIBRARY_PATH:/usr/local/mpi/lib:/usr/lib/x86_64-linux-gnu_custom'" >> ~/.bashrc

COPY ./ /app
