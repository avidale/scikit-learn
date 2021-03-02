# Authors: David Dale dale.david@mail.ru
# License: BSD 3 clause

import numpy as np
from scipy.optimize import linprog

from ..base import BaseEstimator, RegressorMixin
from ._base import LinearModel
from ..utils.validation import _check_sample_weight


class QuantileRegressor(LinearModel, RegressorMixin, BaseEstimator):
    """Linear regression model that predicts conditional quantiles
    and is robust to outliers.

    The Quantile Regressor optimizes the skewed absolute loss
    ``(y - X'w) (q - [y - X'w < 0])``, where q is the desired quantile.

    Optimization is performed as a sequence of smooth optimization problems.

    Read more in the :ref:`User Guide <quantile_regression>`

    .. versionadded:: 0.25

    Parameters
    ----------
    quantile : float, strictly between 0.0 and 1.0, default 0.5
        The quantile that the model predicts.

    alpha : float, default 0.0001
        Constant that multiplies L1 penalty term.

    fit_intercept : bool, default True
        Whether or not to fit the intercept. This can be set to False
        if the data is already centered around the origin.

    normalize : boolean, optional, default False
        This parameter is ignored when ``fit_intercept`` is set to False.
        If True, the regressors X will be normalized before regression by
        subtracting the mean and dividing by the l2-norm.

    copy_X : boolean, optional, default True
        If True, X will be copied; else, it may be overwritten.

    Attributes
    ----------
    coef_ : array, shape (n_features,)
        Features got by optimizing the Huber loss.

    intercept_ : float
        Bias.

    n_iter_ : int
        Number of iterations that scipy.optimize.linprog has run for.

    References
    ----------
    .. [1] Koenker, R., & Bassett Jr, G. (1978). Regression quantiles.
            Econometrica: journal of the Econometric Society, 33-50.

    .. [2] Chen, C., & Wei, Y. (2005).
           Computational issues for quantile regression.
           Sankhya: The Indian Journal of Statistics, 399-417.
    """

    def __init__(
            self,
            quantile=0.5,
            alpha=0.0001,
            fit_intercept=True,
            normalize=False,
            copy_X=True,
            method='revised simplex',
            solver_options=None,
    ):
        self.quantile = quantile
        self.alpha = alpha
        self.fit_intercept = fit_intercept
        self.copy_X = copy_X
        self.normalize = normalize
        self.method = method
        self.solver_options = solver_options

    def fit(self, X, y, sample_weight=None):
        """Fit the model according to the given training data.

        Parameters
        ----------
        X : array-like, shape (n_samples, n_features)
            Training vector, where n_samples in the number of samples and
            n_features is the number of features.

        y : array-like, shape (n_samples,)
            Target vector relative to X.

        sample_weight : array-like, shape (n_samples,)
            Weight given to each sample.

        Returns
        -------
        self : object
            Returns self.
        """

        X, y = self._validate_data(X, y, accept_sparse=['csr'],
                                   y_numeric=True, multi_output=False)

        X, y, X_offset, y_offset, X_scale = self._preprocess_data(
            X, y, self.fit_intercept, self.normalize, self.copy_X,
            sample_weight=sample_weight)

        sample_weight = _check_sample_weight(sample_weight, X)

        if self.quantile >= 1.0 or self.quantile <= 0.0:
            raise ValueError(
                "Quantile should be strictly between 0.0 and 1.0, got %f"
                % self.quantile)

        n_obs, n_slopes = X.shape
        n_params = n_slopes

        X_full = X
        if self.fit_intercept:
            n_params += 1
            X_full = np.concatenate([np.ones([n_obs, 1]), X], axis=1)

        # the linear programming formulation of quantile regression
        # follows https://stats.stackexchange.com/questions/384909/
        c_vector = np.concatenate([
            np.ones(n_params * 2) * self.alpha,
            sample_weight * self.quantile,
            sample_weight * (1 - self.quantile),
        ])
        # do not penalize the intercept
        if self.fit_intercept:
            c_vector[0] = 0
            c_vector[n_params] = 0

        a_eq_matrix = np.concatenate([
            X_full,
            -X_full,
            np.eye(n_obs),
            -np.eye(n_obs),
        ], axis=1)
        b_eq_vector = y

        result = linprog(
            c=c_vector,
            A_eq=a_eq_matrix,
            b_eq=b_eq_vector,
            method=self.method,
            options=self.solver_options
        )
        # todo: check the optimization result for convergence

        params_pos = result.x[:n_params]
        params_neg = result.x[n_params:2 * n_params]
        params = params_pos - params_neg

        self.n_iter_ = result.nit

        self.coef_ = params[self.fit_intercept:]
        # do not use self.set_intercept_, because it assumes intercept is zero
        # if the data is normalized, which is false in this case
        if self.fit_intercept:
            self.coef_ = self.coef_ / X_scale
            self.intercept_ = params[0] + y_offset \
                              - np.dot(X_offset, self.coef_.T)
        else:
            self.intercept_ = 0.0
        return self
