from distutils.core import setup

setup(
    name='hichew',
    version='0.0',
    install_requires=[
        'setuptools',
        'requests',
        'pandas',
        'numpy',
        'lxml',
        'h5py',
        'tqdm',
        'jupyter',
        'scipy',
        'Cython',
        'cooler',
        'cooltools',
        'scikit-learn==1.5.0',
        'seaborn==0.9.0',
        'matplotlib',
    ]
)
