import matplotlib as mpl
mpl.use('Agg') # To fix issue with QXcbConnection: Could not connect to display and Aborted (core dumped)
import matplotlib.pyplot as plt
plt.ioff() # http://matplotlib.org/faq/usage_faq.html (interactive mode)
import numpy as np
import os
import utils

import cntk as C
from cntk import Trainer
from cntk.layers import default_options
from cntk.initializer import he_normal
from cntk.layers import AveragePooling, BatchNormalization, LayerNormalization, Convolution, ConvolutionTranspose2D, Dense
from cntk.ops import element_times, relu, leaky_relu, reduce_mean
import cntk.device
from cntk.io import (MinibatchSource, ImageDeserializer, CTFDeserializer, StreamDef, StreamDefs,
                     INFINITELY_REPEAT)
from cntk.learners import (adam, UnitType, learning_rate_schedule,
                           momentum_as_time_constant_schedule, momentum_schedule)
from cntk.logging import ProgressPrinter, TensorBoardProgressWriter

import cntk.io.transforms as xforms

L1_lambda = 10
isFast = True
# training config
MINIBATCH_SIZE = 128
NUM_MINIBATCHES = 5000 if isFast else 10000
LR = 0.0002
MOMENTUM = 0.5  # equivalent to beta1

# Creates a minibatch source for training or testing
def create_mb_source(map_file, image_dims, num_classes, randomize=True):
    transforms = [
        xforms.scale(width=image_dims[2], height=image_dims[1], channels=image_dims[0], interpolations='linear')]
    return MinibatchSource(ImageDeserializer(map_file, StreamDefs(
        features=StreamDef(field='image', transforms=transforms),
        labels=StreamDef(field='label', shape=num_classes))),
                           randomize=randomize)
def conv(input, filter_size, num_filters, strides=(1,1), init=he_normal()):
    c = Convolution(filter_size, num_filters, activation=None, init=init, pad=True, strides=strides, bias=False)(input)
    return c

def conv_bn(input, filter_size, num_filters, strides=(1,1), init=he_normal()):
    c = Convolution(filter_size, num_filters, activation=None, init=init, pad=True, strides=strides, bias=False)(input)
    r = BatchNormalization(map_rank=1, normalization_time_constant=4096, use_cntk_engine=False)(c)
    return r

def conv_layernorm(input, filter_size, num_filters, strides=(1,1), init=he_normal()):
    c = Convolution(filter_size, num_filters, activation=None, init=init, pad=True, strides=strides, bias=False)(input)
    r = LayerNormalization()(c)
    return r

def conv_bn_relu(input, filter_size, num_filters, strides=(1,1), init=he_normal()):
    r = conv_bn(input, filter_size, num_filters, strides, init)
    return relu(r)

def conv_bn_leaky_relu(input, filter_size, num_filters, strides=(1,1), init=he_normal()):
    r = conv_bn(input, filter_size, num_filters, strides, init)
    return leaky_relu(r)

def conv_leaky_relu(input, filter_size, num_filters, strides=(1,1), init=he_normal()):
    r = conv(input, filter_size, num_filters, strides, init)
    return leaky_relu(r)


def conv_frac_bn(input, filter_size, num_filters, strides=(1,1), init=he_normal()):
    c = ConvolutionTranspose2D(filter_size, num_filters, activation=None, init=init, pad=True, strides=strides, bias=False)(input)
    r = BatchNormalization(map_rank=1, normalization_time_constant=4096, use_cntk_engine=False)(c)
    return r

def conv_fract_bn_relu(input, filter_size, num_filters, strides=(1,1), init=he_normal()):
    r = conv_frac_bn(input, filter_size, num_filters, strides, init)
    return relu(r)

def resblock_basic(input, num_filters):
    c1 = conv_layernorm(input, (3,3), num_filters)
    c2 = conv_layernorm(c1, (3, 3), num_filters)
    return relu(c2)

def resblock_basic_stack(input, num_stack_layers, num_filters):
    assert (num_stack_layers >= 0)
    l = input
    for _ in range(num_stack_layers):
        l = resblock_basic(l, num_filters)
    return l

def generator(h0):
    with default_options(init=C.normal(scale=0.02)):
        print('Generator input shape: ', h0.shape)

        # c7s1-32,d64,d128,R128,R128,R128, R128,R128,R128,R128,R128,R128,u64,u32,c7s1-3
        # c7s1-32
        h1 = conv_bn_relu(h0, (7,7), 32)
        print('h1 shape', h1.shape)

        # d64
        h2 = conv_bn_relu(h1, (3,3), 64, strides=(2,2))
        print('h2 shape', h2.shape)

        # d128
        h3 = conv_bn_relu(h2, (3,3), 128, strides=(2,2))
        print('h3 shape', h3.shape)

        # R128 x 9
        h4 = resblock_basic_stack(h3, 9, 128)
        print('h4 shape', h4.shape)

        # u64
        h5 = conv_fract_bn_relu(h4, (3,3), 64, (2, 2))
        print('h5 shape', h5.shape)

        # u32
        h6 = conv_fract_bn_relu(h5, (3,3), 32, (2, 2))
        print('h6 shape', h6.shape)

        # c7s1-3
        h7 = conv_bn_relu(h6, (7,7), 3)
        print('h7 shape', h7.shape)
        return h7



def discriminator(h0):
    with default_options(init=C.normal(scale=0.02)):
        print('Discriminator input shape: ', h0.shape)

        h1 = conv_leaky_relu(h0, (4,4), 64, strides=(2,2))
        print('h1 shape', h1.shape)

        h2 = conv_bn_leaky_relu(h1, (4,4), 128, strides=(2,2))
        print('h2 shape', h2.shape)

        h3 = conv_bn_leaky_relu(h2, (4,4), 256, strides=(2,2))
        print('h3 shape', h3.shape)

        h4 = conv_bn_leaky_relu(h3, (4,4), 512, strides=(2,2))
        print('h4 shape', h4.shape)

        h5 = conv(h4, (1,1), 1, strides=(1,1))
        print('h5 shape', h5.shape)

if __name__=='__main__':

    num_channels, image_height, image_width = (3, 256, 256)
    h0 = C.input((num_channels, image_height, image_width))
    genG = generator(h0)
    disc = discriminator(h0)
    # DEFINE OUR MODEL AND LOSS FUNCTIONS
    # -------------------------------------------------------

    real_X = None # read images
    real_Y = None # TBD

def dummy():
    # genG(X) => Y            - fake_B
    genG = generator(real_X, name="generatorG")
    # genF(Y) => X            - fake_A
    genF = generator(real_Y, name="generatorF")
    # genF( genG(Y) ) => Y    - fake_A_
    genF_back = generator(genG, name="generatorF", reuse=True)
    # genF( genG(X)) => X     - fake_B_
    genG_back = generator(genF, name="generatorG", reuse=True)

    # DY_fake is the discriminator for Y that takes in genG(X)
    # DX_fake is the discriminator for X that takes in genF(Y)
    discY_fake = discriminator(genG, reuse=False, name="discY")
    discX_fake = discriminator(genF, reuse=False, name="discX")

    g_loss_G = reduce_mean((discY_fake - np.ones(discY_fake)) ** 2) \
            + L1_lambda * reduce_mean(np.abs(real_X - genF_back)) \
            + L1_lambda * reduce_mean(np.abs(real_Y - genG_back))

    g_loss_F = reduce_mean((discX_fake - np.ones(discX_fake)) ** 2) \
            + L1_lambda * reduce_mean(np.abs(real_X - genF_back)) \
            + L1_lambda * reduce_mean(np.abs(real_Y - genG_back))

    input_dynamic_axes = [C.Axis.default_batch_axis()]
    fake_X_sample = C.input((3, 256, 256),  input_dynamic_axes)
    fake_Y_sample = C.input((3, 256, 256),  input_dynamic_axes)

    # DY is the discriminator for Y that takes in Y
    # DX is the discriminator for X that takes in X
    DY = discriminator(real_Y, reuse=True, name="discY")
    DX = discriminator(real_X, reuse=True, name="discX")
    DY_fake_sample = discriminator(fake_Y_sample, reuse=True, name="discY")
    DX_fake_sample = discriminator(fake_X_sample, reuse=True, name="discX")

    softL_c =1
    DY_loss_real = reduce_mean((DY - np.ones_like(DY) * np.abs(np.random.normal(1.0, softL_c))) ** 2)
    DY_loss_fake = reduce_mean((DY_fake_sample - np.zeros_like(DY_fake_sample)) ** 2)
    DY_loss = (DY_loss_real + DY_loss_fake) / 2

    DX_loss_real = reduce_mean((DX - np.ones_like(DX) * np.abs(np.random.normal(1.0, softL_c))) ** 2)
    DX_loss_fake = reduce_mean((DX_fake_sample - np.zeros_like(DX_fake_sample)) ** 2)
    DX_loss = (DX_loss_real + DX_loss_fake) / 2

    test_X = None # TBD read images
    test_Y = None # TBD read images

    testG = generator(test_X,  name="generatorG", reuse=True)
    testF = generator(test_Y,  name="generatorF", reuse=True)
    testF_back = generator(testG, name="generatorF", reuse=True)
    testG_back = generator(testF, name="generatorG", reuse=True)

    print('Optimizing')
    DX_optim= adam(DX_loss.parameters,
        lr=learning_rate_schedule(LR, UnitType.sample),
        momentum=momentum_schedule(0.5))

    DY_optim = adam(DY_loss.parameters,
                    lr=learning_rate_schedule(LR, UnitType.sample),
                    momentum=momentum_schedule(0.5))
    G_optim = adam(g_loss_G.parameters,
                    lr=learning_rate_schedule(LR, UnitType.sample),
                    momentum=momentum_schedule(0.5))

    F_optim = adam(g_loss_F.parameters,
                    lr=learning_rate_schedule(LR, UnitType.sample),
                    momentum=momentum_schedule(0.5))

    for train_step in range(NUM_MINIBATCHES):
        generated_X, generated_Y = sess.run([genF, genG])
        _, _, _, _, summary_str = sess.run([G_optim, DY_optim, F_optim, DX_optim, summary_op],
                                   feed_dict={fake_Y_sample: cache_Y.fetch(generated_Y),
                                              fake_X_sample: cache_X.fetch(generated_X)})




