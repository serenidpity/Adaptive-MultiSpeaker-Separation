# -*- coding: utf-8 -*-
import h5py
import numpy as np
import data_tools
import os
import config
from tqdm import tqdm 
import copy
import time
"""
Class used to have a consistent Randomness between Training/Validation/Test for
different batch size
"""
class ConsistentRandom:
	def __init__(self, seed):
		# Create a new Random State and save the current one
		self.previous_state = np.random.get_state()
		np.random.seed(seed)
		self.state = np.random.get_state()

	def __enter__(self):
		# Apply the new state
		np.random.set_state(self.state)

	def __exit__(self, exc_type, exc_value, traceback):
		# Restore the previous state
		np.random.set_state(self.previous_state)


class Dataset(object):

	def __init__(self, ratio=[0.90, 0.05, 0.05], **kwargs):
		"""
		Inputs:
			ratio: ratio for train / valid / test set
			kwargs: Dataset parameters
		"""

		np.random.seed(config.seed)

		self.nb_speakers = kwargs['nb_speakers']
		self.sex = kwargs['sex']
		self.batch_size = kwargs['batch_size']
		self.chunk_size = kwargs['chunk_size']
		self.no_random_picking = kwargs['no_random_picking']

		# Flags for Training/Validation/Testing sets
		self.TRAIN = 0
		self.VALID = 1
		self.TEST = 2

		# TODO 
		metadata = data_tools.read_metadata()

		if self.sex != ['M', 'F'] and self.sex != ['F', 'M'] and self.sex != ['M'] and self.sex != ['F']:
			raise Exception('Sex must be ["M","F"] |  ["F","M"] | ["M"] | [F"]')

		# Create a key to speaker index dictionnary
		# And count the numbers of speakers
		self.key_to_index = {}
		self.sex_to_keys = {}
		j = 0

		if 'M' in self.sex:
			M = data_tools.males_keys(metadata)
			self.sex_to_keys['M'] = M
			for k in M:
				self.key_to_index[k] = j
				j += 1 
		if 'F' in self.sex:
			F = data_tools.females_keys(metadata)
			self.sex_to_keys['F'] = F
			for k in F:
				self.key_to_index[k] = j
				j += 1

		self.tot_speakers = j

		self.file = h5py.File(kwargs['dataset'], 'r')


		# Define all the items related to each key/speaker
		self.total_items = []

		for key in self.key_to_index.keys():
			for val in self.file[key]:
				# Get one file related to a speaker and check how many chunks can be obtained
				# with the current chunk size
				chunks = self.file['/'.join([key,val])].shape[0]//self.chunk_size
				# Add each possible chunks in the items with the following form:
				# 'key/file/#chunk'
				self.total_items += ['/'.join([key,val,str(i)]) for i in range(chunks)]

		np.random.shuffle(self.total_items)
		self.total_items = self.total_items

		L = len(self.total_items)
		# Shuffle all the items

		# Training / Valid / Test Separation
		train = self.create_tree(self.total_items[:int(L*ratio[0])])
		valid = self.create_tree(self.total_items[int(L*ratio[0]):int(L*(ratio[0]+ratio[1]))])
		test = self.create_tree(self.total_items[int(L*(ratio[0]+ratio[1])):])
		self.items = [train, valid, test]

	def __iter__(self):
		self.used = copy.deepcopy(self.items[self.index])
		return self

	def create_tree(self, items_list):

		items = {'M':{}, 'F':{}}
		tot = {'M':0, 'F':0}

		# Putting Men items in 'M' dictionnary and Female items in the 'F' one
		for item in tqdm(items_list, desc='Creating Dataset'):
			splits = item.split('/')
			key = splits[0] # Retrieve key
			for s in self.sex:
				if key in self.sex_to_keys[s]:
					if key in items[s]:
						items[s][key].append(item)
					else:
						items[s][key] = [item]
					tot[s] += 1
					break

		# Balancing Women and Men items
		if len(self.sex) > 1:
			if tot['M'] < tot['F']:
				D = tot['F'] - tot['M']
				K = items['F'].keys()
				L = len(K)
				for i in range(D):
					l = items['F'][K[i%L]]
					l.remove(np.random.choice(l))
					if len(l) == 0:
						del items['F'][K[i%L]]
					tot['F'] -= 1
			else:
				D = tot['M'] - tot['F']
				K = items['M'].keys()
				L = len(K)
				for i in range(D):
					l = items['M'][K[i%L]]
					l.remove(np.random.choice(l))
					if len(l) == 0:
						del items['M'][K[i%L]]
					tot['M'] -= 1

		items['tot'] = tot['F'] + tot['M']
		return items

	"""
	Getting a batch from the selected set
	Inputs:
		- index: index of the set self.TRAIN / self.TEST / self.VALID 
		- batch_size
		- fake: True -> Do not return anything (used to count the nb of total batches in an epoch) 
	"""
	def get_batch(self, index, batch_size, fake=False):
		with ConsistentRandom(config.seed):
			used = copy.deepcopy(self.items[index])
			while True:
				mix = [[] for _ in range(batch_size)]
				non_mix = [[] for _ in range(batch_size)]
				I = [[] for _ in range(batch_size)]
				for i in range(batch_size):
					if fake: 
						self.next_item(used, fake)
					else: 
						m, n_m, ind = self.next_item(used, fake)
						mix[i] = m
						non_mix[i] = n_m
						I[i] = ind
				mix = np.array(mix)
				non_mix = np.array(non_mix)
				yield (mix, non_mix, I)

	def next_item(self, used, fake=False):

		# Random picking or regular picking or the speaker sex
		if not self.no_random_picking or len(self.sex) == 1:
			genre = np.random.choice(self.sex, self.nb_speakers)
		else:
			genre = np.array(['M' if i%2 == 0 else 'F' for i in range(self.nb_speakers)])

		mix = []
		for s in self.sex:
			nb = sum(map(int,genre == s)) # Get the occurence # of 's' in the mix

			# If there is not enough items left, we cannot create new mixtures
			# It's the end of the current epoch
			if nb > len(used[s].keys()):
				raise StopIteration()

			# Select random keys in each sex
			keys = np.random.choice(used[s].keys(), nb, replace=False)

			for key in keys:
				# Select a random chunk and remove it from the list
				choice = np.random.choice(used[s][key])	
				mix.append(choice)
				used[s][key].remove(choice)
				if len(used[s][key]) == 0:
					del used[s][key]

		if not fake:
			mix_array = np.zeros((self.chunk_size))
			non_mix_array = [[] for _ in range(len(mix))]
			indices = [[] for _ in range(len(mix))]

			# Mixing all the items
			for i, m in enumerate(mix):
				splits = m.split('/')
				key_index = self.key_to_index[splits[0]]
				chunk = int(splits[-1])
				item_path = '/'.join(splits[:-1])

				item = self.file[item_path][chunk*self.chunk_size:(chunk+1)*self.chunk_size]
				mix_array += item

				non_mix_array[i] = item 
				indices[i] = key_index

			return mix_array, non_mix_array, indices

	"""
	Counts the number of batches in the Training Set
	"""
	def nb_batch(self, batch_size):
		i = 0 
		for _ in tqdm(self.get_batch(self.TRAIN, batch_size, fake=True), desc='Counting batches'):
			i+=1
		return i

	@staticmethod
	def create_raw_audio_dataset(output_fn, subset=config.data_subset, data_root=config.data_root):
		"""
		Create a H5 file from the LibriSpeech dataset and the subset given:

		Inputs:
			output_fn: filename for the created file
			subset: LibriSpeech subset : 'dev-clean' , ...
			data_root: LibriSpeech folder path

		"""
		from librosa.core import resample,load

		# Extract the information about this subset (speakers, chapters)
		# Dictionary with the following shape: 
		# {speaker_key: {chapters: [...], sex:'M/F', ... } }
		speakers_info = data_tools.read_metadata(subset)
		with h5py.File(output_fn,'w') as data_file:

			for key, elements in tqdm(speakers_info.items(), total=len(speakers_info), desc='Speakers'):
				if key not in data_file:
					# Create an H5 Group for each key/speaker
					data_file.create_group(key)

				# Current speaker folder path
				folder = data_root+'/'+subset+'/'+key
				# For all the chapters read by this speaker
				for i, chapter in enumerate(tqdm(elements['chapters'], desc='Chapters')): 
					# Find all .flac audio
					for root, dirs, files in os.walk(folder+'/'+chapter): 
						for file in tqdm(files, desc='Files'):
							if file.endswith(".flac"):
								path = os.path.join(root,file)
								raw_audio, sr = load(path, sr=16000)
								raw_audio = resample(raw_audio, sr, config.fs)
								data_file[key].create_dataset(file,
									shape=raw_audio.shape,
									data=raw_audio,
									chunks=raw_audio.shape,
									maxshape=raw_audio.shape,
									compression="gzip",
									compression_opts=9)

		print 'Dataset for the subset: ' + subset + ' has been built'

def create_mix(output_fn, chunk_size, batch_size, nb_speakers, sex, no_random_picking):
	# Extract the information about this subset (speakers, chapters)
	# Dictionary with the following shape: 
	# {speaker_key: {chapters: [...], sex:'M/F', ... } }
	data = Dataset(dataset="h5py_files/train-clean-100-8-s.h5", 
		chunk_size=chunk_size, 
		batch_size=batch_size, 
		nb_speakers=nb_speakers,
		sex=sex,
		no_random_picking=no_random_picking)

	with h5py.File(output_fn,'w') as data_file:

		f = [("train", data.TRAIN),("test",data.TEST), ("valid",data.VALID)]

		for group_name, data_split in f:
			print group_name
			data_file.create_group(group_name)
			train_mix = data_file[group_name].create_dataset("mix",
							shape=(batch_size, chunk_size),
							maxshape=(None, chunk_size),
							compression="gzip",
							chunks=(64, chunk_size),
							dtype='float32')
			train_non_mix = data_file[group_name].create_dataset("non_mix",
							shape=(batch_size, nb_speakers, chunk_size),
							maxshape=(None, nb_speakers, chunk_size),
							compression="gzip",
							chunks=(64, nb_speakers, chunk_size),
							dtype='float32')
			train_index = data_file[group_name].create_dataset("ind",
							shape=(batch_size, nb_speakers),
							maxshape=(None, nb_speakers),
							compression="gzip",
							chunks=(64, nb_speakers),
							dtype='int32')
			size = batch_size
			for i ,(mix, non_mix, index) in enumerate(data.get_batch(data_split, batch_size)):
				train_mix[i*batch_size:(i+1)*batch_size] = mix
				train_non_mix[i*batch_size:(i+1)*batch_size] = non_mix
				train_index[i*batch_size:(i+1)*batch_size] = index
				
				size = size + batch_size
				train_mix.resize((size, chunk_size))
				train_non_mix.resize((size, nb_speakers, chunk_size))
				train_index.resize((size, nb_speakers))

import tensorflow as tf

def create_tfrecord_file(output_fn, chunk_size, batch_size, nb_speakers, sex, no_random_picking):
	# Extract the information about this subset (speakers, chapters)
	# Dictionary with the following shape: 
	# {speaker_key: {chapters: [...], sex:'M/F', ... } }
	data = Dataset(dataset="h5py_files/train-clean-100-8-s.h5", 
		chunk_size=chunk_size, 
		batch_size=batch_size, 
		nb_speakers=nb_speakers,
		sex=sex,
		no_random_picking=no_random_picking)

	f = [("train", data.TRAIN),("test",data.TEST), ("valid",data.VALID)]

	for group_name, data_split in f:
		
		writer = tf.python_io.TFRecordWriter(group_name +'.tfrecords')
		print group_name
		for i ,(mix, non_mix, index) in enumerate(data.get_batch(data_split, batch_size)):
			mix_raw = mix[0].astype(np.float32).tostring()
			non_mix_raw = non_mix[0].astype(np.float32).tostring()
			index = np.array(index[0]).tostring()

			feature = tf.train.Example(features=tf.train.Features(
							feature = { 'chunk_size':tf.train.Feature(int64_list=tf.train.Int64List(value=[chunk_size])),
										'nb_speakers':tf.train.Feature(int64_list=tf.train.Int64List(value=[nb_speakers])),
										'mix':tf.train.Feature(bytes_list=tf.train.BytesList(value=[mix_raw])),
										'non_mix':tf.train.Feature(bytes_list=tf.train.BytesList(value=[non_mix_raw])),
										'ind':tf.train.Feature(bytes_list=tf.train.BytesList(value=[index]))
									}))

			writer.write(feature.SerializeToString())

		writer.close()


def decode(serialized_example):
	features = tf.parse_single_example(
		serialized_example,
		features={
			'chunk_size': tf.FixedLenFeature([], tf.int64),
			'nb_speakers': tf.FixedLenFeature([], tf.int64),
			'mix':tf.FixedLenFeature([], tf.string),
			'non_mix':tf.FixedLenFeature([], tf.string),
			'ind': tf.FixedLenFeature([], tf.string),
		})

	chunk_size = tf.cast(features['chunk_size'], tf.int32)
	nb_speakers = tf.cast(features['nb_speakers'], tf.int32)

	ind = tf.decode_raw(features['ind'], tf.int64)
	ind = tf.cast(ind, tf.int32)
	ind = tf.reshape(ind, [nb_speakers])

	mix = tf.decode_raw(features['mix'], tf.float32)
	mix = tf.reshape(mix,[chunk_size])

	non_mix = tf.decode_raw(features['non_mix'], tf.float32)
	non_mix = tf.reshape(non_mix, [nb_speakers, chunk_size])

	return mix, non_mix, ind

def mapping(dataset, batch_size):
	dataset = dataset.apply(tf.contrib.data.map_and_batch(
    	map_func=decode, 
    	batch_size=tf.placeholder_with_default(tf.constant(batch_size, dtype=tf.int64), ()),
		num_parallel_batches=8))
	return dataset.prefetch(1)

class TFDataset(object):

	def __init__(self, **kwargs):
		batch_size = kwargs['batch_size']

		training_dataset = tf.data.TFRecordDataset('train.tfrecords')
		training_dataset = mapping(training_dataset, batch_size)

		validation_dataset = tf.data.TFRecordDataset('valid.tfrecords')
		validation_dataset = mapping(validation_dataset, batch_size)

		test_dataset = tf.data.TFRecordDataset('test.tfrecords')
		test_dataset = mapping(test_dataset, batch_size)

		self.handle = tf.placeholder(tf.string, shape=[])
		iterator = tf.data.Iterator.from_string_handle(
			self.handle, training_dataset.output_types, training_dataset.output_shapes)
		self.next_element = iterator.get_next()

		self.training_iterator = training_dataset.make_initializable_iterator()
		self.validation_iterator = validation_dataset.make_initializable_iterator()
		self.test_iterator = test_dataset.make_initializable_iterator()

		self.training_initializer = self.training_iterator.initializer
		self.validation_initializer = self.validation_iterator.initializer
		self.test_initializer = self.test_iterator.initializer

		self.next_mix, self.next_non_mix, self.next_ind = self.next_element

	def init_handle(self):
		sess = tf.get_default_session()
		self.training_handle = sess.run(self.training_iterator.string_handle())
		self.validation_handle = sess.run(self.validation_iterator.string_handle())
		self.test_handle = sess.run(self.test_iterator.string_handle())

	def get_handle(self, split):
		if split == 'train':
			return self.training_handle
		elif split == 'valid':
			return self.validation_handle
		elif split == 'test':
			return self.test_handle

	def get_initializer(self, split):
		if split == 'train':
			return self.training_initializer
		elif split == 'valid':
			return self.validation_initializer
		elif split == 'test':
			return self.test_initializer

	def length(self, split):
		count = 0
		sess = tf.get_default_session()
		sess.run(self.get_initializer(split))
		try:
			while True:
				sess.run(self.next_element, feed_dict={self.handle: self.get_handle(split)})
				count += 1
		except Exception:
			return count

	def initialize(self, sess, split):
		sess.run(self.initializer,feed_dict={self.split: split})

if __name__ == "__main__":
	###
	### TEST
	##
	create_tfrecord_file("testou.h5", 20480, 1, 2, ['M','F'], True)
	# ds = TFDataset(batch_size=3)

	# with tf.Session().as_default() as sess:
	# 	ds.init_handle()
	# 	L = ds.length('train')
	# 	print L, ds.length('test'), ds.length('valid')
	# 	sess.run(ds.training_initializer)
	# 	for i in range(L):
	# 		value = sess.run(ds.next_element, feed_dict={ds.handle: ds.get_handle('train')})
	# 		print value[0].shape