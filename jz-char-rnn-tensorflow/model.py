import tensorflow as tf
from tensorflow.models.rnn import rnn_cell,rnn
from tensorflow.models.rnn import seq2seq
from jz_rnn_cell import *

import numpy as np

class Model():
    def __init__(self, args, infer=False):
        self.args = args
        if infer:
            args.batch_size = 1
            args.seq_length = 1

        if args.model == 'rnn': cell_fn = jzRNNCell
        elif args.model == 'gru': cell_fn = jzGRUCell
        elif args.model == 'lstm': cell_fn = jzLSTMCell
        else: raise Exception("model type not supported: {}".format(args.model))

        if args.activation == 'tanh': cell_af = tf.tanh
        elif args.activation == 'sigmoid': cell_af = tf.sigmoid
        elif args.activation == 'relu': cell_af = tf.nn.relu
        else: raise Exception("activation function not supported: {}".format(args.activation))

        self.input_data = tf.placeholder(tf.int32, [args.batch_size, args.seq_length])
        self.targets = tf.placeholder(tf.int32, [args.batch_size, args.seq_length])

        with tf.variable_scope('rnnlm'):
            if not args.bidirectional:
                softmax_w = tf.get_variable("softmax_w", [args.rnn_size, args.vocab_size])
            else:
                softmax_w = tf.get_variable("softmax_w", [args.rnn_size*2, args.vocab_size])
            softmax_b = tf.get_variable("softmax_b", [args.vocab_size])
            with tf.device("/cpu:0"):
                embedding = tf.get_variable("embedding", [args.vocab_size, args.rnn_size])
                inputs = tf.split(1, args.seq_length, tf.nn.embedding_lookup(embedding, self.input_data))
                inputs = [tf.nn.dropout(tf.squeeze(input_, [1]),args.dropout) for input_ in inputs]

        # one-directional RNN (nothing changed here..)
        if not args.bidirectional:
            cell = cell_fn(args.rnn_size,activation=cell_af)
            self.cell = cell = rnn_cell.MultiRNNCell([cell] * args.num_layers)
            self.initial_state = cell.zero_state(args.batch_size, tf.float32)
            def loop(prev, _):
                prev = tf.matmul(prev, softmax_w) + softmax_b
                prev_symbol = tf.stop_gradient(tf.argmax(prev, 1))
                return tf.nn.embedding_lookup(embedding, prev_symbol)
            outputs, last_state = seq2seq.rnn_decoder(inputs, self.initial_state, cell, loop_function=loop if infer else None, scope='rnnlm')
            output = tf.reshape(tf.concat(1, outputs), [-1, args.rnn_size])

        # bi-directional RNN
        else:
            lstm_fw = cell_fn(args.rnn_size,activation=cell_af)
            lstm_bw = cell_fn(args.rnn_size,activation=cell_af)
            self.lstm_fw = lstm_fw = rnn_cell.MultiRNNCell([lstm_fw]*args.num_layers)
            self.lstm_bw = lstm_bw = rnn_cell.MultiRNNCell([lstm_bw]*args.num_layers)
            self.initial_state_fw = lstm_fw.zero_state(args.batch_size,tf.float32)
            self.initial_state_bw = lstm_bw.zero_state(args.batch_size,tf.float32)
            outputs,_,_ = rnn.bidirectional_rnn(lstm_fw, lstm_bw, inputs,
                                            initial_state_fw=self.initial_state_fw,
                                            initial_state_bw=self.initial_state_bw,
                                                sequence_length=args.batch_size) 
            output = tf.reshape(tf.concat(1, outputs), [-1, args.rnn_size*2])

        self.logits = tf.matmul(tf.nn.dropout(output,args.dropout), softmax_w) + softmax_b
        self.probs = tf.nn.softmax(self.logits)
        loss = seq2seq.sequence_loss_by_example([self.logits],
                [tf.reshape(self.targets, [-1])],
                [tf.ones([args.batch_size * args.seq_length])],
                args.vocab_size)
        self.cost = tf.reduce_sum(loss) / args.batch_size / args.seq_length
        self.final_state = last_state
        self.lr = tf.Variable(0.0, trainable=False)
        tvars = tf.trainable_variables()
        grads, _ = tf.clip_by_global_norm(tf.gradients(self.cost, tvars),
                args.grad_clip)
        optimizer = tf.train.AdamOptimizer(self.lr)
        self.train_op = optimizer.apply_gradients(zip(grads, tvars))

    def sample(self, sess, chars, vocab, num=200, prime='The ', sampling_type=1):
        state = self.cell.zero_state(1, tf.float32).eval()
        for char in prime[:-1]:
            x = np.zeros((1, 1))
            x[0, 0] = vocab[char]
            feed = {self.input_data: x, self.initial_state:state}
            [state] = sess.run([self.final_state], feed)

        def weighted_pick(weights):
            t = np.cumsum(weights)
            s = np.sum(weights)
            return(int(np.searchsorted(t, np.random.rand(1)*s)))

        ret = prime
        char = prime[-1]
        for n in range(num):
            x = np.zeros((1, 1))
            x[0, 0] = vocab[char]
            feed = {self.input_data: x, self.initial_state:state}
            [probs, state] = sess.run([self.probs, self.final_state], feed)
            p = probs[0]

            if sampling_type == 0:
                sample = np.argmax(p)
            elif sampling_type == 2:
                if char == ' ':
                    sample = weighted_pick(p)
                else:
                    sample = np.argmax(p)
            else: # sampling_type == 1 default:
                sample = weighted_pick(p)

            pred = chars[sample]
            ret += pred
            char = pred
        return ret
