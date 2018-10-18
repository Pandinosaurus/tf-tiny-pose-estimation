# Copyright 2018 Jaewook Kang (jwkang10@gmail.com)
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ======================
#-*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function


import tensorflow as tf
import tensorflow.contrib.slim as slim
import numpy as np

class ModelBuilder(object):

    def __init__(self,model_config):
        self._model_config = model_config
        self.dropout_keeprate = tf.placeholder(dtype=tf.float32)




    def get_model(self, model_in,scope):

        with tf.variable_scope(name_or_scope=scope, values=[model_in]):
            recept_out = self._get_reception_layer(ch_in                       =model_in,
                                                   num_outputs                  =self._model_config.channel_num,
                                                   model_config                 =self._model_config.reception,
                                                   model_config_separable_conv  =self._model_config.separable_conv,
                                                   scope                        ='reception')
            # -----------------------------------------------------
            hg_out,hg_out_stack = self._get_hourglass_layer(ch_in                       =recept_out,
                                                            model_config                 =self._model_config.hourglass,
                                                            model_config_separable_conv  =self._model_config.separable_conv,
                                                            scope                        ='hourglass')
            # -----------------------------------------------------

            # with tf.variable_scope(name_or_scope='hg_layer',values=[recept_out]):
            #     hg_out = self._get_hourglass_layer( ch_in                       =recept_out,
            #                                         model_config                 =self._model_config.hourglass,
            #                                         model_config_separable_conv  =self._model_config.separable_conv,
            #                                         scope                        ='hourglass')
            #     hg_out  = tf.add(recept_out,hg_out)


            model_out = self._get_output_layer(ch_in                    =hg_out,
                                               num_outputs              =self._model_config.output_chnum,
                                               model_config             =self._model_config.output,
                                               scope                    ='output')

        tf.logging.info('[ModelBuilder] model building complete')
        tf.logging.info('[ModelBuilder] model output shape = %s'%model_out.shape)


        return model_out,hg_out_stack
        # return model_out







    def _get_reception_layer(self,ch_in,
                            num_outputs,
                            model_config,
                            model_config_separable_conv,
                            scope='recept'):

        with tf.variable_scope(name_or_scope=scope,values=[ch_in]):
            with slim.arg_scope([model_config.normalizer_fn],
                                decay=model_config.batch_norm_decay,
                                fused=model_config.batch_norm_fused,
                                is_training=model_config.is_trainable,
                                activation_fn=model_config.activation_fn):

                net = slim.conv2d(inputs                =ch_in,
                                  num_outputs           =num_outputs,
                                  kernel_size           =model_config.kernel_shape['r1'],
                                  stride                =model_config.strides['r1'],
                                  weights_initializer   =model_config.weights_initializer,
                                  weights_regularizer   =model_config.weights_regularizer,
                                  biases_initializer    =model_config.biases_initializer,
                                  normalizer_fn         =model_config.normalizer_fn,
                                  activation_fn         =None,
                                  padding               ='SAME',
                                  scope                 ='7x7conv')


            net = self._get_inverted_bottleneck(ch_in           =net,
                                                ch_out_num      =num_outputs,
                                                model_config    =model_config_separable_conv,
                                                scope='inverted_bottleneck')

            net = slim.max_pool2d(inputs=net,
                                  kernel_size   =model_config.kernel_shape['r4'],
                                  stride        =model_config.strides['r4'],
                                  padding       ='SAME',
                                  scope='maxpool')

        return net






    def _get_output_layer(self,ch_in,
                         num_outputs,
                         model_config,
                         scope='output'):


        with tf.variable_scope(name_or_scope=scope, values=[ch_in]):
            out = slim.conv2d(inputs                =ch_in,
                              num_outputs           =num_outputs,
                              kernel_size           =model_config.kernel_shape,
                              stride                =model_config.stride,
                              weights_initializer   =model_config.weights_initializer,
                              weights_regularizer   =model_config.weights_regularizer,
                              normalizer_fn         =None,
                              activation_fn         =None,
                              padding               ='SAME',
                              trainable             =model_config.is_trainable,
                              scope='1x1conv')

            if model_config.dropout_keeprate < 1.0:
                out = slim.dropout(inputs= out,
                                   keep_prob=self.dropout_keeprate)

            out = model_config.normalizer_fn(  inputs= out,
                                                decay       =model_config.batch_norm_decay,
                                                fused       =model_config.batch_norm_fused,
                                                is_training =model_config.is_trainable,
                                                activation_fn=model_config.activation_fn,
                                                scope       ='batch_norm_outlayer')


        return out






    def _get_hourglass_layer(self,ch_in,
                            model_config,
                            model_config_separable_conv,
                            scope='hourglass'):

        input_shape     = ch_in.get_shape().as_list()
        ch_in_num       = input_shape[3]
        output_shape    = [input_shape[1],input_shape[2]]

        with tf.variable_scope(name_or_scope=scope,values=[ch_in]):

            downsample_out_stack = []
            net = ch_in
            for down_index in range(0,model_config.num_stage):
                net = self.downsample_hourglass(ch_in                       =net,
                                                model_config                =model_config,
                                                model_config_separable_conv =model_config_separable_conv,
                                                scope                       ='downsample_'+str(down_index))
                downsample_out_stack.append(net)

            # center
            center = slim.repeat(net,model_config.center_conv_num,self._get_inverted_bottleneck,
                                 ch_out_num=model_config.center_ch_num,
                                 model_config=model_config_separable_conv,
                                 scope='inverted_bottleneck')


            # add skip connection
            net = center
            hourglass_output_stack = []
            for up_index in range(0,model_config.num_stage):

                skip_connection = downsample_out_stack.pop()
                skip_connection = slim.repeat(skip_connection,model_config.skip_conv_num,self._get_inverted_bottleneck,
                                              ch_out_num=model_config.center_ch_num,
                                              model_config=model_config_separable_conv,
                                              scope='invbo_skip_'+str(up_index))


                net = tf.add(x=net, y=skip_connection)
                #---------------------------------#
                with tf.variable_scope(name_or_scope='resized_hgout',values=[net]):
                    resized_net = tf.image.resize_bilinear(images = net,
                                                           size = output_shape,
                                                           align_corners=False,
                                                           name=        'resize_for_extra_loss')

                    hourglass_output_stack.append(resized_net)
                #---------------------------------#

                net = self.upsample_hourglass(ch_in                         =net,
                                              model_config                  =model_config,
                                              model_config_separable_conv   =model_config_separable_conv,
                                              scope                         ='upsample_'+str(up_index))

            ## -------------------------------------
            with tf.variable_scope(name_or_scope='skip_connect_io',values=[ch_in]):
                skip_connection = slim.repeat(ch_in,model_config.skip_conv_num,self._get_inverted_bottleneck,
                                              ch_out_num=model_config.center_ch_num,
                                              model_config=model_config_separable_conv,
                                              scope='skip_connect_io')
                net = tf.add(skip_connection,net)
            ## -------------------------------------


        return net, hourglass_output_stack

        # return net


    # def _get_dense_hourglass_layer(self,ch_in,
    #                                 model_config,
    #                                 model_config_separable_conv,
    #                                 scope='hourglass'):
    #
    #
    #     return net


    def downsample_hourglass(self,ch_in,
                             model_config,
                             model_config_separable_conv,
                             scope='downsample'):

        ch_in_num   = ch_in.get_shape().as_list()[3]
        with tf.variable_scope(name_or_scope=scope,values=[ch_in]):

            net = self._get_inverted_bottleneck(ch_in       = ch_in,
                                                ch_out_num  = ch_in_num,
                                                model_config= model_config_separable_conv,
                                                scope       = 'inverted_bottleneck')
            net = slim.max_pool2d(inputs        =net,
                                  kernel_size   =model_config.maxpool_kernel_size,
                                  stride        =model_config.updown_rate,
                                  padding       ='SAME',
                                  scope='maxpool')

        return net






    def upsample_hourglass(self,ch_in,
                                model_config,
                                model_config_separable_conv,
                                scope='upsample'):

        input_shape     = ch_in.get_shape().as_list()
        output_shape    = [int(input_shape[1]*model_config.updown_rate),
                           int(input_shape[2]*model_config.updown_rate)]

        ch_in_num   = input_shape[3]
        with tf.variable_scope(name_or_scope=scope,values=[ch_in]):
            net = tf.image.resize_bilinear(images       =ch_in,
                                           size         =output_shape,
                                           align_corners=False,
                                           name         ='resize')

            net = self._get_inverted_bottleneck(ch_in       =net,
                                            ch_out_num  =ch_in_num,
                                            model_config=model_config_separable_conv,
                                            scope       ='inverted_bottleneck')

        return net






    def _get_separable_conv2d(self,ch_in,
                                ch_out_num,
                                model_config,
                                scope='separable_conv'):

        conv2d_padding = 'SAME'
        net = ch_in
        kernel_size  = model_config.kernel_shape_dwise
        stride       = model_config.stride_dwise

        with tf.variable_scope(name_or_scope=scope, default_name='separable_conv2d', values=[ch_in]):
            with slim.arg_scope([model_config.normalizer_fn],
                                decay       =model_config.batch_norm_decay,
                                fused       =model_config.batch_norm_fused,
                                is_training =model_config.is_trainable,
                                activation_fn=None):
                '''
                    Note that "slim.separable_convolution2cd with num_outputs == None" 
                    provides equivalent implementation to the depthwise convolution 
                    with ch_in_num == ch_out_num
                '''
                # depthwise conv with 3x3 kernal
                net = slim.separable_convolution2d(inputs               =net,
                                                   num_outputs          =None,
                                                   kernel_size          =kernel_size,
                                                   depth_multiplier     =1.0,
                                                   stride               =[stride, stride],
                                                   padding              =conv2d_padding,
                                                   activation_fn        =None,
                                                   normalizer_fn        =model_config.normalizer_fn,
                                                   biases_initializer   =None,
                                                   weights_initializer  =model_config.weights_initializer,
                                                   weights_regularizer  =model_config.weights_regularizer,
                                                   trainable            =model_config.is_trainable,
                                                   scope                =scope + '_dwise_conv')
                # intermediate activation
                if model_config.activation_fn_dwise is not None:
                    net = model_config.activation_fn_dwise(net)

                # pointwise conv with 1x1 kernal
                net = slim.conv2d(inputs                =net,
                                  num_outputs           =ch_out_num,
                                  kernel_size           =[1, 1],
                                  stride                =[1, 1],
                                  padding               ='SAME',
                                  activation_fn         =None,
                                  normalizer_fn         =model_config.normalizer_fn,
                                  biases_initializer    =None,
                                  weights_initializer   =model_config.weights_initializer,
                                  weights_regularizer   =model_config.weights_regularizer,
                                  trainable             =model_config.is_trainable,
                                  scope                 =scope + '_pwise_conv')

                # output activation
                if model_config.activation_fn_pwise is not None:
                    net = model_config.activation_fn_pwise(net)

        return net





    def _get_inverted_bottleneck(self,ch_in,
                                ch_out_num,
                                model_config,
                                scope='inverted_bottleneck'):

        conv2d_padding = 'SAME'
        net = ch_in
        kernel_size  = model_config.kernel_shape_dwise
        stride       = model_config.stride_dwise

        # number of input channel
        ch_in_num       = ch_in.get_shape().as_list()[3]
        expand_ch_num   = np.floor(ch_in_num * model_config.invbottle_expansion_rate)
        with tf.variable_scope(name_or_scope=scope, default_name='inverted_bottleneck', values=[ch_in]) as sc:

            with slim.arg_scope([slim.conv2d],
                                kernel_size=[1, 1],
                                stride=[1, 1],
                                padding='SAME',
                                activation_fn=None,
                                weights_initializer=model_config.weights_initializer,
                                weights_regularizer=None,
                                trainable=model_config.is_trainable):

                with slim.arg_scope([model_config.normalizer_fn],
                                    decay=model_config.batch_norm_decay,
                                    fused=model_config.batch_norm_fused,
                                    is_training=model_config.is_trainable,
                                    activation_fn=model_config.activation_fn_pwise):

                    # linear bottleneck by conv 1x1
                    # followed by batch_norm and relu6

                    net = slim.conv2d(inputs=net,
                                      num_outputs=expand_ch_num,
                                      normalizer_fn=model_config.normalizer_fn,
                                      biases_initializer=None,
                                      scope=scope + '_bottleneck')

                    '''
                        Note that "slim.separable_convolution2cd with num_outputs == None" 
                        provides equivalent implementation to the depthwise convolution 
                        with ch_in_num == ch_out_num
                    '''
                    # depthwise conv with 3x3 conv
                    # followed by batch_norm and relu6
                    net = slim.separable_convolution2d(inputs=net,
                                                       num_outputs=None,
                                                       kernel_size=kernel_size,
                                                       depth_multiplier=1.0,
                                                       stride=[stride, stride],
                                                       padding=conv2d_padding,
                                                       activation_fn=None,
                                                       normalizer_fn=model_config.normalizer_fn,
                                                       biases_initializer=None,
                                                       weights_initializer=model_config.weights_initializer,
                                                       weights_regularizer=model_config.weights_regularizer,
                                                       trainable=model_config.is_trainable,
                                                       scope=scope + '_dwise_conv')

                    # pointwise conv with 1x1 kernal
                    # followed by batch_norm
                    net = slim.conv2d(inputs=net,
                                      num_outputs=ch_out_num,
                                      normalizer_fn=None,
                                      biases_initializer=model_config.biases_initializer,
                                      scope=scope + '_pwise_conv')

                    net = model_config.normalizer_fn(inputs=net,
                                                     activation_fn=None)

                ch_in_shape = ch_in.get_shape().as_list()
                ch_in_num = ch_in_shape[3]

                # shortcut connection
                if ch_in_num != ch_out_num:
                    shortcut_out = slim.conv2d(inputs=ch_in,
                                               num_outputs=ch_out_num,
                                               normalizer_fn=None,
                                               biases_initializer=model_config.biases_initializer,
                                               scope=scope + '_shortcut_conv1x1')
                else:
                    shortcut_out = ch_in

                if stride > 1:
                    shortcut_out = slim.max_pool2d(inputs=shortcut_out,
                                                   kernel_size=[3,3],
                                                   stride=[stride, stride],
                                                   padding=conv2d_padding,
                                                   scope=scope + '_shortcut_maxpool')



            # elementwise sum for shortcut connection
            net = tf.add(x=shortcut_out,
                         y=net,
                         name=scope + '_out')


        return net

    # def show_model_shape(self):
