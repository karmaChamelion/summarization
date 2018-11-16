import json
from nltk.tokenize import RegexpTokenizer
import numpy as np
from datetime import datetime
import random

import model.summarization_args as summarization_args


def read_docs(args, type_):
    filename = type_ + '_model.json' if args.full_test else "small_" + type_ + '_model.json'
    filename = '../data/'+ args.source + '_' + str(args.vocab_size) + '_' + filename

    with open(filename, 'rb') as data_file:
        data = json.load(data_file)

    ret_data = [data['x'], data['y'], data['e'], data['clean_y'], data['sha'], data['mask'], data['chunk'], data['scut']]

    if type_ != 'train':
        ret_data.append(data['raw_x'])
    else:
        ret_data.append(None)

    return ret_data


def create_vocab(args):
    vocab_map = dict()
    vocab_ls = []

    ifp = open('../data/' + str(args.source) + '_vocab_' + str(args.vocab_size) + '.txt', 'r')

    for line in ifp:
        w = line.rstrip()
        vocab_map[w] = len(vocab_map)
        vocab_ls.append(w)

    ifp.close()

    return vocab_map, vocab_ls


def create_stopwords(args, vocab_map, lst_words):
    ifp = open(args.stopwords, 'r')
    stopwords = set()
    punctuation = set()

    # Add stopwords
    for line in ifp:
        w = line.rstrip()

        if w in vocab_map:
            stopwords.add(vocab_map[w])

    ifp.close()

    tokenizer = RegexpTokenizer(r'\w+')

    # add punctuation
    for i in xrange(len(lst_words)):
        w = lst_words[i]

        if len(tokenizer.tokenize(w)) == 0:
            punctuation.add(i)

    record_stopwords(stopwords, punctuation, lst_words)

    return stopwords, punctuation


def create_batches(args, x, y, entities, clean_indexed_y, sha, padding_id,
                   stopwords, sort=True, model_type=''):

    batch_size = args.batch
    batches_x, batches_y, batches_entities,  batches_sha = [], [], [], []

    N = len(x)
    M = (N - 1) / batch_size + 1
    num_batches = 0
    num_files = 0

    if sort is not None:
        if sort == 'sort':
            perm = range(N)
            perm = sorted(perm, key=lambda i: len(x[i]))
        elif sort == 'shuffle':
            random.seed(datetime.now())

            perm = range(N)
            random.shuffle(perm)

        else:
            raise NotImplementedError

        x = [x[i] for i in perm]
        y = [y[i] for i in perm]
        entities = [entities[i] for i in perm]
        clean_indexed_y = [clean_indexed_y[i] for i in perm]
        sha = [sha[i] for i in perm]

    for i in xrange(M):
        single_batch_x, single_batch_y = create_one_batch(
            args,
            x[i * batch_size:(i + 1) * batch_size],
            y[i * batch_size:(i + 1) * batch_size],
            clean_indexed_y[i * batch_size:(i + 1) * batch_size],
            padding_id,
            stopwords
        )
        single_batch_sha = sha[i * batch_size:(i + 1) * batch_size]
        single_batch_entities = entities[i * batch_size:(i + 1) * batch_size]

        batches_x.append(single_batch_x)
        batches_y.append(single_batch_y)
        batches_entities.append(single_batch_entities)
        batches_sha.append(single_batch_sha)

        num_batches += 1

        if num_batches >= args.online_batch_size or i == M - 1:
            fname = args.batch_dir + args.source + model_type
            print 'Creating file #', str(num_files + 1)

            data = [batches_x, batches_y, batches_entities, batches_sha]

            with open(fname + str(num_files), 'w+') as ofp:
                np.save(ofp, data)

            batches_x, batches_y, batches_entities, batches_sha = [], [], [], []

            num_batches = 0
            num_files += 1

    print "Num Files :", num_files


def create_one_batch(args, lst_x, lst_y, lst_clean_y, padding_id, stopwords):
    max_len = args.inp_len

    assert min(len(x) for x in lst_x) > 0

    single_batch_y, unigrams = process_hl(args, lst_y, padding_id, lst_clean_y)
    single_batch_y = np.column_stack([y for y in single_batch_y])

    lst_x = prune_x(args, lst_x, unigrams, stopwords, max_len)

    single_batch_x = np.column_stack([np.pad(x[:max_len], (0, max_len - len(x) if len(x) <= max_len else 0), "constant",
                                             constant_values=padding_id).astype('int32') for x in lst_x])

    return single_batch_x, single_batch_y


def stack_pt(args, lspt, padding_id_pt):
    num_samples = len(lspt)
    bmpt = []
    for i in xrange(num_samples):
        for j in xrange(args.inp_len):
            if j < len(lspt[i]):
                x = len(lspt[i][j])

                bmpt.append(np.pad(lspt[i][j][-args.pt_len:], (args.pt_len - x if x <= args.pt_len else 0, 0), "constant",
                                   constant_values=padding_id_pt).astype('int32'))
            else:
                x = 0
                bmpt.append(np.pad([], (args.pt_len - x if x <= args.pt_len else 0, 0), "constant",
                                   constant_values=padding_id_pt).astype('int32'))

            assert len(bmpt[-1]) == args.pt_len

    return np.column_stack([m for m in bmpt])


def process_hl(args, lsty, padding_id, lstcy):
    max_len_y = args.hl_len

    y_processed = [[] for _ in xrange(args.n)]

    unigrams = []

    for i in xrange(len(lsty)):
        sample_u = set()

        for j in xrange(len(lsty[i])):
            if j == args.n:
                break
            y = lsty[i][j][:max_len_y]
            single_hl = np.pad(y, (0, max_len_y - len(y)), "constant", constant_values=padding_id).astype('int32')

            y_processed[j].append(single_hl)

        for j in range(len(lsty[i]), args.n):
            y_processed[j].append(np.full((max_len_y,), fill_value=padding_id).astype('int32'))

        for clean_hl in lstcy[i]:
            trimmed_cy = clean_hl[:max_len_y]

            for token in trimmed_cy:
                sample_u.add(token)

        unigrams.append(sample_u)

    by = []
    for i in xrange(len(y_processed)):
        by.extend(y_processed[i])

    return by, unigrams


def pad_sentences(args, padding_id, lstx):
    s_len = args.inp_len_sent
    lstx_batch_flat = []

    for sample in lstx:
        flattened_sample = []

        for sentence in sample:
            cur_s_len = len(sentence)

            if cur_s_len >= s_len:
                flattened_sample.extend(sentence[:s_len])
            else:
                padding = [padding_id] * (s_len - cur_s_len)
                flattened_sample.extend(sentence)
                flattened_sample.extend(padding)
                assert len(padding) + cur_s_len == s_len

        lstx_batch_flat.append(flattened_sample)

    return lstx_batch_flat


def stack_p_vec(max_x, sent_bounds, x, padding_id):
    position_idx_batch = []

    for a_idx in xrange(len(x)):
        position_idx_x = []
        total_x = 0
        cur_encoding = 0

        for sent_len in sent_bounds[a_idx]:
            cur_s = [cur_encoding] * sent_len

            position_idx_x.extend(cur_s)

            total_x += sent_len
            cur_encoding += 1

            if total_x > max_x:
                position_idx_x = position_idx_x[:max_x]
                break

        if len(position_idx_x) < max_x:
            position_idx_x.extend([padding_id] * (max_x - len(position_idx_x)))

        position_idx_batch.append(position_idx_x)

    return np.column_stack([j for j in position_idx_batch]).astype('int32')


def prune_x(args, lst_x, unigrams, stopwords, max_len):
    updated_x = []

    for i in xrange(len(lst_x)):
        len_x = len(lst_x[i])
        updated_single_doc = []

        if args.use_overlap:
            for j in xrange(len_x - 1):

                if j >= max_len:
                    break
                w1 = lst_x[i][j]
                w2 = lst_x[i][j+1]

                if w1 in unigrams[i] and w2 in unigrams[i]:
                    if contains_single_valid_word(w1, w2, stopwords):
                        try:
                            updated_single_doc.append(w1)
                            updated_single_doc.append(w2)
                        except IndexError:
                            continue
        else:
            for j in xrange(len_x):
                draw = random.uniform(0, 1)

                if draw <= args.x_sample_percentage:
                    updated_single_doc.append(lst_x[i][j])

        updated_x.append(updated_single_doc)

    return updated_x


def contains_single_valid_word(w1, w2, stopwords):
    sw = stopwords[0]
    punct = stopwords[1]

    if w1 in punct or w2 in punct:
        return False

    if w1 in sw and w2 in sw:
        return False

    return True


def process_ent(n_classes, lste):
    ret_e = []

    for e in lste:
        e_mask = np.zeros((n_classes,),dtype='int32')

        for e_idx in e:
            e_mask[e_idx] = 1

        ret_e.append(e_mask)

    return ret_e


def record_stopwords(stopwords, punctuation, lst_words):
    ofp = open('../data/stopword_map.json', 'w+')
    data = dict()

    for w_idx in stopwords:
        data[w_idx] = lst_words[w_idx]

    json_d = dict()
    json_d['stopwords'] = data
    data = dict()

    for w_idx in punctuation:
        data[w_idx] = lst_words[w_idx]

    json_d['punctuation'] = data
    json.dump(json_d, ofp)

    ofp.close()


def flatten_data(args, cur_data):
    y_counts = []
    items = len(cur_data)
    new_data = [[] for _ in xrange(items)]

    if cur_data[-1] is None:
        items = items - 1
        new_data[-1] = None

    for i in xrange(len(cur_data[1])):
        used_y = min(args.n, len(cur_data[1][i]))
        y_counts.append(used_y)

        for j in xrange(used_y):

            for k in range(1, 3):
                new_data[k].append([cur_data[k][i][j]])

            num_clean_y = len(cur_data[3][i])
            cy_copy = []
            for cy in xrange(num_clean_y):
                cy_copy.append(cur_data[3][i][cy][:])

            new_data[3].append(cy_copy)

            for k in [0] + range(4, items):
                if isinstance(cur_data[k][i], list):
                    new_data[k].append(cur_data[k][i][:])
                else:
                    new_data[k].append(cur_data[k][i])

    return new_data


def main(args):
    vocab_map, lst_words = create_vocab(args)
    stopwords = create_stopwords(args, vocab_map, lst_words)

    pad_id = vocab_map["<padding>"]

    del vocab_map
    del lst_words

    type_ls = ['train', 'dev', 'test']
    sort_ls = [args.sort, None, None]

    for type_, sort in zip(type_ls, sort_ls):
        print type_, ':'
        print '  (QA) Read JSON..'
        cur_data = read_docs(args, type_)

        create_batches(args=args,
                       x=cur_data[0],
                       y=cur_data[1],
                       entities=cur_data[2],
                       clean_indexed_y=cur_data[3],
                       sha=cur_data[4],
                       padding_id=pad_id,
                       stopwords=stopwords,
                       sort=sort,
                       model_type=type_)

        print '  Purge references..'
        del cur_data
        print '  Finished', type_


if __name__ == "__main__":
    args = summarization_args.get_args()
    main(args)