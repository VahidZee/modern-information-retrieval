from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.manifold import TSNE
from sklearn.mixture import GaussianMixture
from sklearn.metrics import adjusted_rand_score, adjusted_mutual_info_score
from sklearn.metrics.cluster import contingency_matrix
from sklearn.decomposition import PCA
import matplotlib.pyplot as plt
import pandas as pd
from src.text_processing import persian_terms
import functools
from sklearn.feature_extraction.text import TfidfVectorizer
from gensim.models import Word2Vec
import numpy as np
from collections import defaultdict
from tqdm import tqdm
import itertools


def number_classes(column):
    label_mapping = {label: i for i, label in enumerate(column.unique())}
    return label_mapping


def load_data(file='./files/hamshahri.json', stem=False, lemmatize=True, remove_conjunctions=False, join=' '):
    # reading raw data
    data = pd.read_json(file, encoding='utf-8')

    # separating minor and major tags
    data['major_cls'], data['minor_cls'] = zip(*data['tags'].map(lambda x: tuple(x[0].split('>'))))
    major_labels, minor_labels = number_classes(data['major_cls']), number_classes(data['minor_cls'])
    data['major_cls'] = data['major_cls'].apply(lambda x: major_labels[x])
    data['minor_cls'] = data['minor_cls'].apply(lambda x: minor_labels[x])

    # mixing title and summary and calculating terms list
    data['terms'] = (data['title'] + ' ' + data['summary']).apply(
        functools.partial(persian_terms, stem=stem, lemmatize=lemmatize, remove_conjunctions=remove_conjunctions,
                          join=join))
    return data, major_labels, minor_labels


def purity_score(y_true, y_pred):
    matrix = contingency_matrix(y_true, y_pred)
    return np.sum(np.amax(matrix, axis=0)) / np.sum(matrix)


def evaluate_clustering(true_labels, predicted_labels):
    return {
        'purity': purity_score(true_labels, predicted_labels),
        'adjusted_mutual_info': adjusted_mutual_info_score(true_labels, predicted_labels),
        'adjusted_rand_index': adjusted_rand_score(true_labels, predicted_labels),
    }


def vectorize(data, w2v_options=None, tf_idf_options=None):
    w2v_options = w2v_options or dict(workers=8, iter=100)
    tf_idf_options = tf_idf_options or dict()
    vectorizer = TfidfVectorizer(**tf_idf_options)
    tf_idf = vectorizer.fit_transform(data['terms'])

    model = Word2Vec(data['terms'].apply(lambda x: x.split(' ')), **w2v_options)
    w2v = np.array(data['terms'].apply(
        lambda x: sum(model.wv[y] if y in model.wv else 0 for y in x.split(' ')) / len(x.split(' '))).to_list())
    return tf_idf, w2v


def plot_values(x, series: dict, xlabel=None, ylabel=None, title=None, legend=True, ):
    for label, values in series.items():
        plt.plot(x, values, label=label)

    if xlabel:
        plt.xlabel(xlabel)
    if ylabel:
        plt.ylabel(ylabel)
    if title:
        plt.title(title)
    plt.grid()
    if legend:
        plt.legend()
    plt.show()


def _submit_result(result, vec_type, metrics, variables):
    for met, met_val in metrics.items():
        for var, var_val in variables.items():
            result[var].append(var_val)
        result['metric'].append(met)
        result['score'].append(met_val)
        result['vectorization'].append(vec_type)


def gridsearch_hyperparams(algorithm, data, tfidf=None, w2v=None, fixed_params=None, variables=None):
    result = defaultdict(list)

    var_keys = list(variables.keys())
    fixed_params = fixed_params or dict()
    variables = variables or dict()

    vectors = []
    if tfidf is not None:
        vectors.append(('tf-idf', tfidf))
    if w2v is not None:
        vectors.append(('w2v', w2v))

    for vals in tqdm(list(itertools.product(*[variables[key] for key in var_keys]))):
        cur_vars = dict()
        for i, key in enumerate(var_keys):
            cur_vars[key] = vals[i]

        for vec_name, vec in vectors:
            try:
                labels, sizes = algorithm(data, vec, **fixed_params, **cur_vars)
                eval_res = evaluate_clustering(data['major_cls'], labels)
                _submit_result(result, vec_name, eval_res, cur_vars)
            except Exception:
                pass
    return pd.DataFrame(result)


def kmeans(data, vectors, n_components=None, **kwargs):
    n_components = len(data['major_cls'].unique()) if n_components is None else n_components
    model = KMeans(n_components, **kwargs)
    labels = model.fit_predict(vectors)
    return labels, None


def hierarchical(data, vectors, n_components=None, **kwargs):
    n_components = len(data['major_cls'].unique()) if n_components is None else n_components
    model = AgglomerativeClustering(n_components, **kwargs)
    labels = model.fit_predict(vectors)
    return labels, None


def GMM(data, vectors, n_components=None, **kwargs):
    n_components = len(data['major_cls'].unique()) if n_components is None else n_components
    model = GaussianMixture(n_components, **kwargs)
    model.fit(vectors)
    sizes = model.predict_proba(vectors)
    return model.predict(vectors), sizes


def cluster(data, algorithm, tfidf=None, w2v=None, options=None, options_tfidf=None, options_w2v=None, save=False):
    options = options or dict()
    options_tfidf = options_tfidf or dict()
    options_w2v = options_w2v or dict()
    result = pd.DataFrame({'link': data['link']})

    if tfidf is not None:
        args = {**options, **options_tfidf}
        name = f'{algorithm.__name__.capitalize()}' + ('' if not options else (
                ' (' + ','.join(f'{i}={j}' for i, j in args.items()) + ')'))
        result['tf-idf'], sizes = algorithm(data, tfidf, **args)
        plot2d(tfidf, result['tf-idf'], true_labels=data['major_cls'], sizes=sizes, title=f'{name} [tf-idf]')
    if w2v is not None:
        args = {**options, **options_w2v}
        name = f'{algorithm.__name__.capitalize()}' + ('' if not options else (
                ' (' + ','.join(f'{i}={j}' for i, j in args.items()) + ')'))
        result['w2v'], sizes = algorithm(data, w2v, **args)
        plot2d(w2v, result['w2v'], true_labels=data['major_cls'], sizes=sizes, title=f'{name} [w2v]')
    if save:
        result[['link', 'tf-idf']].rename(columns={'link': 'link', 'tf-idf': 'pred'}).to_csv(
            f'outputs/{algorithm.__name__.lower()}-tfidf.csv')
        result[['link', 'w2v']].rename(columns={'link': 'link', 'w2v': 'pred'}).to_csv(
            f'outputs/{algorithm.__name__.lower()}-w2v.csv')
    return result


def pca(n_components, vectors, random_state=666):
    pca = PCA(n_components, random_state=random_state)
    return pca.fit_transform(vectors)


def evaluate_results(kmeans_res=None, gmm_res=None, hier_res=None, data=None):
    res = defaultdict(list)
    for name, value in [('kmeans', kmeans_res), ('gmm', gmm_res), ('hierarchical', hier_res)]:
        if value is None:
            continue
        for vectorization in ['tf-idf', 'w2v']:
            res['algorithm'].append(name.capitalize())
            res['vectorization'].append(vectorization)
            alres = evaluate_clustering(data['major_cls'], value[vectorization])
            for metric, metric_value in alres.items():
                res[metric].append(metric_value)
    return pd.DataFrame(res)


def tsne(n_components, vectors):
    return TSNE(n_components=n_components).fit_transform(vectors)


def plot2d(vectors, labels, true_labels=None, sizes=None, title=None):
    vecs = pca(2, vectors)
    tsne_vecs = tsne(2, vectors)
    if sizes is not None:
        sizes = sizes - sizes.min()
        sizes = (sizes / sizes.max()) * 40 + 10
    if true_labels is not None:
        fig, axes = plt.subplots(1, 4, figsize=(28, 4.8))
        axes[0].scatter(vecs[:, 0], vecs[:, 1], c=labels, s=sizes)
        axes[0].set_title('Prediction (PCA)')
        axes[1].scatter(tsne_vecs[:, 0], tsne_vecs[:, 1], c=labels, s=sizes)
        axes[1].set_title('Prediction (TSNE)')
        axes[2].scatter(vecs[:, 0], vecs[:, 1], c=true_labels)
        axes[2].set_title('Ground truth (PCA)')
        axes[3].scatter(tsne_vecs[:, 0], tsne_vecs[:, 1], c=true_labels)
        axes[3].set_title('Ground truth (TSNE)')
        if title:
            fig.suptitle(title)
        return
    plt.scatter(vecs[:, 0], vecs[:, 1], c=labels, s=sizes)
    if title:
        plt.title(title)
    plt.grid()
    plt.show()
