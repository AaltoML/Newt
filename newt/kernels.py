import objax
from jax import vmap
import jax.numpy as np
from jax.scipy.linalg import cho_factor, cho_solve, block_diag
from .utils import scaled_squared_euclid_dist, softplus, softplus_inv, rotation_matrix
from warnings import warn


class Kernel(objax.Module):
    """
    """

    def __call__(self, X, X2):
        return self.K(X, X2)

    def K(self, X, X2):
        raise NotImplementedError('kernel function not implemented')

    def measurement_model(self):
        raise NotImplementedError

    def inducing_precision(self):
        return None, None

    def kernel_to_state_space(self, R=None):
        raise NotImplementedError

    def spatial_conditional(self, R=None, predict=False):
        """
        """
        return None, None


class StationaryKernel(Kernel):
    """
    """

    def __init__(self,
                 variance=1.0,
                 lengthscale=1.0,
                 fix_variance=False,
                 fix_lengthscale=False):
        # check whether the parameters are to be optimised
        if fix_lengthscale:
            self.transformed_lengthscale = objax.StateVar(softplus_inv(np.array(lengthscale)))
        else:
            self.transformed_lengthscale = objax.TrainVar(softplus_inv(np.array(lengthscale)))
        if fix_variance:
            self.transformed_variance = objax.StateVar(softplus_inv(np.array(variance)))
        else:
            self.transformed_variance = objax.TrainVar(softplus_inv(np.array(variance)))

    @property
    def variance(self):
        return softplus(self.transformed_variance.value)

    @property
    def lengthscale(self):
        return softplus(self.transformed_lengthscale.value)

    def K(self, X, X2):
        r2 = scaled_squared_euclid_dist(X, X2, self.lengthscale)
        return self.K_r2(r2)

    def K_r2(self, r2):
        # Clipping around the (single) float precision which is ~1e-45.
        r = np.sqrt(np.maximum(r2, 1e-36))
        return self.K_r(r)

    @staticmethod
    def K_r(r):
        raise NotImplementedError('kernel not implemented')

    def kernel_to_state_space(self, R=None):
        raise NotImplementedError

    def measurement_model(self):
        raise NotImplementedError

    def state_transition(self, dt):
        raise NotImplementedError

    def stationary_covariance(self):
        raise NotImplementedError


class Matern12(StationaryKernel):
    """
    The Matern 1/2 kernel. Functions drawn from a GP with this kernel are not
    differentiable anywhere. The kernel equation is

    k(r) = ???? exp{-r}

    where:
    r  is the Euclidean distance between the input points, scaled by the lengthscales parameter ???.
    ???? is the variance parameter
    """

    @property
    def state_dim(self):
        return 1

    def K_r(self, r):
        return self.variance * np.exp(-r)

    def kernel_to_state_space(self, R=None):
        F = np.array([[-1.0 / self.lengthscale]])
        L = np.array([[1.0]])
        Qc = np.array([[2.0 * self.variance / self.lengthscale]])
        H = np.array([[1.0]])
        Pinf = np.array([[self.variance]])
        return F, L, Qc, H, Pinf

    def stationary_covariance(self):
        Pinf = np.array([[self.variance]])
        return Pinf

    def measurement_model(self):
        H = np.array([[1.0]])
        return H

    def state_transition(self, dt):
        """
        Calculation of the discrete-time state transition matrix A = expm(F??t) for the exponential prior.
        :param dt: step size(s), ??t??? = t??? - t????????? [scalar]
        :return: state transition matrix A [1, 1]
        """
        A = np.broadcast_to(np.exp(-dt / self.lengthscale), [1, 1])
        return A


class Matern32(StationaryKernel):
    """
    The Matern 3/2 kernel. Functions drawn from a GP with this kernel are once
    differentiable. The kernel equation is

    k(r) = ???? (1 + ???3r) exp{-???3 r}

    where:
    r  is the Euclidean distance between the input points, scaled by the lengthscales parameter ???,
    ???? is the variance parameter.
    """

    @property
    def state_dim(self):
        return 2

    def K_r(self, r):
        sqrt3 = np.sqrt(3.0)
        return self.variance * (1.0 + sqrt3 * r) * np.exp(-sqrt3 * r)

    def kernel_to_state_space(self, R=None):
        lam = 3.0 ** 0.5 / self.lengthscale
        F = np.array([[0.0,       1.0],
                      [-lam ** 2, -2 * lam]])
        L = np.array([[0],
                      [1]])
        Qc = np.array([[12.0 * 3.0 ** 0.5 / self.lengthscale ** 3.0 * self.variance]])
        H = np.array([[1.0, 0.0]])
        Pinf = np.array([[self.variance, 0.0],
                         [0.0, 3.0 * self.variance / self.lengthscale ** 2.0]])
        return F, L, Qc, H, Pinf

    def stationary_covariance(self):
        Pinf = np.array([[self.variance, 0.0],
                         [0.0, 3.0 * self.variance / self.lengthscale ** 2.0]])
        return Pinf

    def measurement_model(self):
        H = np.array([[1.0, 0.0]])
        return H

    def state_transition(self, dt):
        """
        Calculation of the discrete-time state transition matrix A = expm(F??t) for the Matern-3/2 prior.
        :param dt: step size(s), ??t??? = t??? - t????????? [scalar]
        :return: state transition matrix A [2, 2]
        """
        lam = np.sqrt(3.0) / self.lengthscale
        A = np.exp(-dt * lam) * (dt * np.array([[lam, 1.0], [-lam**2.0, -lam]]) + np.eye(2))
        return A


class Matern52(StationaryKernel):
    """
    The Matern 5/2 kernel. Functions drawn from a GP with this kernel are twice
    differentiable. The kernel equation is

    k(r) = ???? (1 + ???5r + 5/3r??) exp{-???5 r}

    where:
    r  is the Euclidean distance between the input points, scaled by the lengthscales parameter ???,
    ???? is the variance parameter.
    """

    @property
    def state_dim(self):
        return 3

    def K_r(self, r):
        sqrt5 = np.sqrt(5.0)
        return self.variance * (1.0 + sqrt5 * r + 5.0 / 3.0 * np.square(r)) * np.exp(-sqrt5 * r)

    def kernel_to_state_space(self, R=None):
        lam = 5.0**0.5 / self.lengthscale
        F = np.array([[0.0, 1.0, 0.0],
                      [0.0, 0.0, 1.0],
                      [-lam**3.0, -3.0*lam**2.0, -3.0*lam]])
        L = np.array([[0.0],
                      [0.0],
                      [1.0]])
        Qc = np.array([[self.variance * 400.0 * 5.0 ** 0.5 / 3.0 / self.lengthscale ** 5.0]])
        H = np.array([[1.0, 0.0, 0.0]])
        kappa = 5.0 / 3.0 * self.variance / self.lengthscale**2.0
        Pinf = np.array([[self.variance,    0.0,   -kappa],
                         [0.0,    kappa, 0.0],
                         [-kappa, 0.0,   25.0*self.variance / self.lengthscale**4.0]])
        return F, L, Qc, H, Pinf

    def measurement_model(self):
        H = np.array([[1.0, 0.0, 0.0]])
        return H

    def state_transition(self, dt):
        """
        Calculation of the discrete-time state transition matrix A = expm(F??t) for the Matern-5/2 prior.
        :param dt: step size(s), ??t??? = t??? - t????????? [scalar]
        :return: state transition matrix A [3, 3]
        """
        lam = np.sqrt(5.0) / self.lengthscale
        dtlam = dt * lam
        A = np.exp(-dtlam) \
            * (dt * np.array([[lam * (0.5 * dtlam + 1.0),      dtlam + 1.0,            0.5 * dt],
                              [-0.5 * dtlam * lam ** 2,        lam * (1.0 - dtlam),    1.0 - 0.5 * dtlam],
                              [lam ** 3 * (0.5 * dtlam - 1.0), lam ** 2 * (dtlam - 3), lam * (0.5 * dtlam - 2.0)]])
               + np.eye(3))
        return A

    def stationary_covariance(self):
        kappa = 5.0 / 3.0 * self.variance / self.lengthscale**2.0
        Pinf = np.array([[self.variance,    0.0,   -kappa],
                         [0.0,    kappa, 0.0],
                         [-kappa, 0.0,   25.0*self.variance / self.lengthscale**4.0]])
        return Pinf


class Matern72(StationaryKernel):
    """
    The Matern 7/2 kernel. Functions drawn from a GP with this kernel are three times differentiable.

    where:
    r  is the Euclidean distance between the input points, scaled by the lengthscales parameter ???,
    ???? is the variance parameter.
    """

    @property
    def state_dim(self):
        return 4

    def K_r(self, r):
        sqrt7 = np.sqrt(7.0)
        return self.variance * (1. + sqrt7 * r + 14. / 5. * np.square(r) + 7. * sqrt7 / 15. * r**3) * np.exp(-sqrt7 * r)

    def kernel_to_state_space(self, R=None):
        # uses variance and lengthscale hyperparameters to construct the state space model
        lam = 7.0**0.5 / self.lengthscale
        F = np.array([[0.0,       1.0,           0.0,           0.0],
                      [0.0,       0.0,           1.0,           0.0],
                      [0.0,       0.0,           0.0,           1.0],
                      [-lam**4.0, -4.0*lam**3.0, -6.0*lam**2.0, -4.0*lam]])
        L = np.array([[0.0],
                      [0.0],
                      [0.0],
                      [1.0]])
        Qc = np.array([[self.variance * 10976.0 * 7.0 ** 0.5 / 5.0 / self.lengthscale ** 7.0]])
        H = np.array([[1, 0, 0, 0]])
        kappa = 7.0 / 5.0 * self.variance / self.lengthscale**2.0
        kappa2 = 9.8 * self.variance / self.lengthscale**4.0
        Pinf = np.array([[self.variance,   0.0,    -kappa, 0.0],
                         [0.0,    kappa,   0.0,    -kappa2],
                         [-kappa, 0.0,     kappa2, 0.0],
                         [0.0,    -kappa2, 0.0,    343.0*self.variance / self.lengthscale**6.0]])
        return F, L, Qc, H, Pinf

    def measurement_model(self):
        H = np.array([[1.0, 0.0, 0.0, 0.0]])
        return H

    def state_transition(self, dt):
        """
        Calculation of the discrete-time state transition matrix A = expm(F??t) for the Matern-7/2 prior.
        :param dt: step size(s), ??t??? = t??? - t????????? [scalar]
        :return: state transition matrix A [4, 4]
        """
        lam = np.sqrt(7.0) / self.lengthscale
        lam2 = lam * lam
        lam3 = lam2 * lam
        dtlam = dt * lam
        dtlam2 = dtlam ** 2
        A = np.exp(-dtlam) \
            * (dt * np.array([[lam * (1.0 + 0.5 * dtlam + dtlam2 / 6.0),      1.0 + dtlam + 0.5 * dtlam2,
                              0.5 * dt * (1.0 + dtlam),                       dt ** 2 / 6],
                              [-dtlam2 * lam ** 2.0 / 6.0,                    lam * (1.0 + 0.5 * dtlam - 0.5 * dtlam2),
                              1.0 + dtlam - 0.5 * dtlam2,                     dt * (0.5 - dtlam / 6.0)],
                              [lam3 * dtlam * (dtlam / 6.0 - 0.5),            dtlam * lam2 * (0.5 * dtlam - 2.0),
                              lam * (1.0 - 2.5 * dtlam + 0.5 * dtlam2),       1.0 - dtlam + dtlam2 / 6.0],
                              [lam2 ** 2 * (dtlam - 1.0 - dtlam2 / 6.0),      lam3 * (3.5 * dtlam - 4.0 - 0.5 * dtlam2),
                              lam2 * (4.0 * dtlam - 6.0 - 0.5 * dtlam2),      lam * (1.5 * dtlam - 3.0 - dtlam2 / 6.0)]])
               + np.eye(4))
        return A

    def stationary_covariance(self):
        kappa = 7.0 / 5.0 * self.variance / self.lengthscale ** 2.0
        kappa2 = 9.8 * self.variance / self.lengthscale ** 4.0
        Pinf = np.array([[self.variance, 0.0, -kappa, 0.0],
                         [0.0, kappa, 0.0, -kappa2],
                         [-kappa, 0.0, kappa2, 0.0],
                         [0.0, -kappa2, 0.0, 343.0 * self.variance / self.lengthscale ** 6.0]])
        return Pinf


class SpatioTemporalKernel(Kernel):
    """
    The Spatio-Temporal GP class
    :param temporal_kernel: the temporal prior, must be a member of the Prior class
    :param spatial_kernel: the kernel used for the spatial dimensions
    :param z: the initial spatial locations
    :param conditional: specifies which method to use for computing the covariance of the spatial conditional;
                        must be one of ['DTC', 'FIC', 'Full']
    :param sparse: boolean specifying whether the model is sparse in space
    :param opt_z: boolean specifying whether to optimise the spatial input locations z
    """
    def __init__(self,
                 temporal_kernel,
                 spatial_kernel,
                 z=None,
                 conditional=None,
                 sparse=True,
                 opt_z=False,
                 spatial_dims=None):
        self.temporal_kernel = temporal_kernel
        self.spatial_kernel = spatial_kernel
        if conditional is None:
            if sparse:
                conditional = 'Full'
            else:
                conditional = 'DTC'
        if opt_z and (not sparse):  # z should not be optimised if the model is not sparse
            warn("spatial inducing inputs z will not be optimised because sparse=False")
            opt_z = False
        self.sparse = sparse
        if z is None:  # initialise z
            # TODO: smart initialisation
            if spatial_dims == 1:
                z = np.linspace(-3., 3., num=15)
            elif spatial_dims == 2:
                z1 = np.linspace(-3., 3., num=5)
                zA, zB = np.meshgrid(z1, z1)  # Adding additional dimension to inducing points grid
                z = np.hstack((zA.reshape(-1, 1), zB.reshape(-1, 1)))  # Flattening grid for use in kernel functions
            else:
                raise NotImplementedError('please provide an initialisation for inducing inputs z')
        if z.ndim < 2:
            z = z[:, np.newaxis]
        if spatial_dims is None:
            spatial_dims = z.ndim - 1
        assert spatial_dims == z.ndim - 1
        self.M = z.shape[0]
        if opt_z:
            self.z = objax.TrainVar(z)  # .reshape(-1, 1)
        else:
            self.z = objax.StateVar(z)
        if conditional in ['DTC', 'dtc']:
            self.conditional_covariance = self.deterministic_training_conditional
        elif conditional in ['FIC', 'FITC', 'fic', 'fitc']:
            self.conditional_covariance = self.fully_independent_conditional
        elif conditional in ['Full', 'full']:
            self.conditional_covariance = self.full_conditional
        else:
            raise NotImplementedError('conditional method not recognised')
        if (not sparse) and (conditional != 'DTC'):
            warn("You chose a non-deterministic conditional, but \'DTC\' will be used because the model is not sparse")

    @property
    def variance(self):
        return self.temporal_kernel.variance

    @property
    def temporal_lengthscale(self):
        return self.temporal_kernel.lengthscale

    @property
    def spatial_lengthscale(self):
        return self.spatial_kernel.lengthscale

    @property
    def state_dim(self):
        return self.temporal_kernel.state_dim

    def K(self, X, X2):
        T = X[:, :1]
        T2 = X2[:, :1]
        R = X[:, 1:]
        R2 = X2[:, 1:]
        return self.temporal_kernel(T, T2) * self.spatial_kernel(R, R2)

    @staticmethod
    def deterministic_training_conditional(X, R, Krz, K):
        cov = np.array([[0.0]])
        return cov

    def fully_independent_conditional(self, X, R, Krz, K):
        Krr = self.spatial_kernel(R, R)
        X = X.reshape(-1, 1)
        cov = self.temporal_kernel.K(X, X) * (np.diag(np.diag(Krr - K @ Krz.T)))
        return cov

    def full_conditional(self, X, R, Krz, K):
        Krr = self.spatial_kernel(R, R)
        X = X.reshape(-1, 1)
        cov = self.temporal_kernel.K(X, X) * (Krr - K @ Krz.T)
        return cov

    def spatial_conditional(self, X=None, R=None, predict=False):
        """
        Compute the spatial conditional, i.e. the measurement model projecting the latent function u(t) to f(X,R)
            f(X,R) | u(t) ~ N(f(X,R) | B u(t), C)
        """
        Qzz, Lzz = self.inducing_precision()  # pre-calculate inducing precision and its Cholesky factor
        if self.sparse or predict:
            # TODO: save compute if R is constant:
            # gridded_data = np.all(np.abs(np.diff(R, axis=0)) < 1e-10)
            # if gridded_data:
            #     R = R[:1]
            R = R.reshape((R.shape[0],) + (-1,) + self.z.value.shape[1:])
            Krz = vmap(self.spatial_kernel, [0, None])(R, self.z.value)
            K = Krz @ Qzz  # Krz / Kzz
            B = K @ Lzz
            C = vmap(self.conditional_covariance)(X, R, Krz, K)  # conditional covariance
        else:
            B = Lzz
            # conditional covariance (deterministic mapping is exact in non-sparse case)
            C = np.zeros([B.shape[0], B.shape[0]])
        return B, C

    def inducing_precision(self):
        """
        Compute the covariance and precision of the inducing spatial points to be used during filtering
        """
        Kzz = self.spatial_kernel(self.z.value, self.z.value)
        Lzz, low = cho_factor(Kzz, lower=True)  # K_zz^(1/2)
        Qzz = cho_solve((Lzz, low), np.eye(self.M))  # K_zz^(-1)
        return Qzz, Lzz

    def stationary_covariance(self):
        """
        Compute the covariance of the stationary state distribution. Since the latent components are independent
        under the prior, this is a block-diagonal matrix
        """
        Pinf_time = self.temporal_kernel.stationary_covariance()
        Pinf = np.kron(np.eye(self.M), Pinf_time)
        return Pinf

    def measurement_model(self):
        """
        Compute the spatial conditional, i.e. the measurement model projecting the state x(t) to function space
            f(t, R) = H x(t)
        """
        H_time = self.temporal_kernel.measurement_model()
        H = np.kron(np.eye(self.M), H_time)
        return H

    def state_transition(self, dt):
        """
        Calculation of the discrete-time state transition matrix A = expm(F??t) for the spatio-temporal prior.
        :param dt: step size(s), ??t??? = t??? - t????????? [scalar]
        :return: state transition matrix A
        """
        A_time = self.temporal_kernel.state_transition(dt)
        A = np.kron(np.eye(self.M), A_time)
        return A

    def kernel_to_state_space(self, R=None):
        F_t, L_t, Qc_t, H_t, Pinf_t = self.temporal_kernel.kernel_to_state_space()
        Kzz = self.spatial_kernel(self.z.value, self.z.value)
        F = np.kron(np.eye(self.M), F_t)
        Qc = None
        L = None
        H = self.measurement_model()
        Pinf = np.kron(Kzz, Pinf_t)
        return F, L, Qc, H, Pinf


class SpatioTemporalMatern12(SpatioTemporalKernel):
    """
    Spatio-Temporal Matern-1/2 kernel in SDE form.
    Hyperparameters:
        variance, ????
        temporal lengthscale, lt
        spatial lengthscale, ls
    """
    def __init__(self,
                 variance=1.0,
                 lengthscale_time=1.0,
                 lengthscale_space=1.0,
                 z=None,
                 sparse=True,
                 opt_z=False,
                 conditional=None):
        super().__init__(temporal_kernel=Matern12(variance=variance, lengthscale=lengthscale_time),
                         spatial_kernel=Matern12(variance=1., lengthscale=lengthscale_space, fix_variance=True),
                         z=z,
                         conditional=conditional,
                         sparse=sparse,
                         opt_z=opt_z)
        self.name = 'Spatio-Temporal Matern-1/2'


class SpatioTemporalMatern32(SpatioTemporalKernel):
    """
    Spatio-Temporal Matern-3/2 kernel in SDE form.
    Hyperparameters:
        variance, ????
        temporal lengthscale, lt
        spatial lengthscale, ls
    """
    def __init__(self,
                 variance=1.0,
                 lengthscale_time=1.0,
                 lengthscale_space=1.0,
                 z=None,
                 sparse=True,
                 opt_z=False,
                 conditional=None):
        super().__init__(temporal_kernel=Matern32(variance=variance, lengthscale=lengthscale_time),
                         spatial_kernel=Matern32(variance=1., lengthscale=lengthscale_space, fix_variance=True),
                         z=z,
                         conditional=conditional,
                         sparse=sparse,
                         opt_z=opt_z)
        self.name = 'Spatio-Temporal Matern-3/2'


class SpatioTemporalMatern52(SpatioTemporalKernel):
    """
    Spatio-Temporal Matern-5/2 kernel in SDE form.
    Hyperparameters:
        variance, ????
        temporal lengthscale, lt
        spatial lengthscale, ls
    """
    def __init__(self,
                 variance=1.0,
                 lengthscale_time=1.0,
                 lengthscale_space=1.0,
                 z=None,
                 sparse=True,
                 opt_z=False,
                 conditional=None):
        super().__init__(temporal_kernel=Matern52(variance=variance, lengthscale=lengthscale_time),
                         spatial_kernel=Matern52(variance=1., lengthscale=lengthscale_space, fix_variance=True),
                         z=z,
                         conditional=conditional,
                         sparse=sparse,
                         opt_z=opt_z)
        self.name = 'Spatio-Temporal Matern-5/2'


class SpatialMatern12(SpatioTemporalKernel):
    """
    Spatial Matern-1/2 kernel in SDE form. Similar to the spatio-temporal kernel but the
    lengthscale is shared across dimensions.
    Hyperparameters:
        variance, ????
        lengthscale, l
    """
    def __init__(self,
                 variance=1.0,
                 lengthscale=1.0,
                 z=None,
                 sparse=True,
                 opt_z=False,
                 conditional=None):
        super().__init__(temporal_kernel=Matern12(variance=variance, lengthscale=lengthscale),
                         spatial_kernel=Matern12(variance=1., lengthscale=lengthscale, fix_variance=True),
                         z=z,
                         conditional=conditional,
                         sparse=sparse,
                         opt_z=opt_z)
        # --- couple the lengthscales ---
        self.spatial_kernel.transformed_lengthscale = self.temporal_kernel.transformed_lengthscale
        # -------------------------------
        self.name = 'Spatial Matern-1/2'


class SpatialMatern32(SpatioTemporalKernel):
    """
    Spatial Matern-3/2 kernel in SDE form. Similar to the spatio-temporal kernel but the
    lengthscale is shared across dimensions.
    Hyperparameters:
        variance, ????
        lengthscale, l
    """
    def __init__(self,
                 variance=1.0,
                 lengthscale=1.0,
                 z=None,
                 sparse=True,
                 opt_z=False,
                 conditional=None):
        super().__init__(temporal_kernel=Matern32(variance=variance, lengthscale=lengthscale),
                         spatial_kernel=Matern32(variance=1., lengthscale=lengthscale, fix_variance=True),
                         z=z,
                         conditional=conditional,
                         sparse=sparse,
                         opt_z=opt_z)
        # --- couple the lengthscales ---
        self.spatial_kernel.transformed_lengthscale = self.temporal_kernel.transformed_lengthscale
        # -------------------------------
        self.name = 'Spatial Matern-3/2'


class SpatialMatern52(SpatioTemporalKernel):
    """
    Spatial Matern-5/2 kernel in SDE form. Similar to the spatio-temporal kernel but the
    lengthscale is shared across dimensions.
    Hyperparameters:
        variance, ????
        lengthscale, l
    """
    def __init__(self,
                 variance=1.0,
                 lengthscale=1.0,
                 z=None,
                 sparse=True,
                 opt_z=False,
                 conditional=None):
        super().__init__(temporal_kernel=Matern52(variance=variance, lengthscale=lengthscale),
                         spatial_kernel=Matern52(variance=1., lengthscale=lengthscale, fix_variance=True),
                         z=z,
                         conditional=conditional,
                         sparse=sparse,
                         opt_z=opt_z)
        # --- couple the lengthscales ---
        self.spatial_kernel.transformed_lengthscale = self.temporal_kernel.transformed_lengthscale
        # -------------------------------
        self.name = 'Spatial Matern-5/2'


class QuasiPeriodicMatern12(Kernel):
    """
    TODO: implement a general 'Product' class to reduce code duplication
    Quasi-periodic kernel in SDE form (product of Periodic and Matern-1/2).
    Hyperparameters:
        variance, ????
        lengthscale of Periodic, l_p
        period, p
        lengthscale of Matern, l_m
    The associated continuous-time state space model matrices are constructed via
    a sum of cosines times a Matern-1/2.
    """
    def __init__(self, variance=1.0, lengthscale_periodic=1.0, period=1.0, lengthscale_matern=1.0, order=6):
        self.transformed_lengthscale_periodic = objax.TrainVar(np.array(softplus_inv(lengthscale_periodic)))
        self.transformed_variance = objax.TrainVar(np.array(softplus_inv(variance)))
        self.transformed_period = objax.TrainVar(np.array(softplus_inv(period)))
        self.transformed_lengthscale_matern = objax.TrainVar(np.array(softplus_inv(lengthscale_matern)))
        super().__init__()
        self.name = 'Quasi-periodic Matern-1/2'
        self.order = order
        self.igrid = np.meshgrid(np.arange(self.order + 1), np.arange(self.order + 1))[1]
        factorial_mesh_K = np.array([[1., 1., 1., 1., 1., 1., 1.],
                                     [1., 1., 1., 1., 1., 1., 1.],
                                     [2., 2., 2., 2., 2., 2., 2.],
                                     [6., 6., 6., 6., 6., 6., 6.],
                                     [24., 24., 24., 24., 24., 24., 24.],
                                     [120., 120., 120., 120., 120., 120., 120.],
                                     [720., 720., 720., 720., 720., 720., 720.]])
        b = np.array([[1., 0., 0., 0., 0., 0., 0.],
                      [0., 2., 0., 0., 0., 0., 0.],
                      [2., 0., 2., 0., 0., 0., 0.],
                      [0., 6., 0., 2., 0., 0., 0.],
                      [6., 0., 8., 0., 2., 0., 0.],
                      [0., 20., 0., 10., 0., 2., 0.],
                      [20., 0., 30., 0., 12., 0., 2.]])
        self.b_fmK_2igrid = b * (1. / factorial_mesh_K) * (2. ** -self.igrid)

    @property
    def variance(self):
        return softplus(self.transformed_variance.value)

    @property
    def lengthscale_periodic(self):
        return softplus(self.transformed_lengthscale_periodic.value)

    @property
    def lengthscale_matern(self):
        return softplus(self.transformed_lengthscale_matern.value)

    @property
    def period(self):
        return softplus(self.transformed_period.value)

    def K(self, X, X2):
        raise NotImplementedError

    def kernel_to_state_space(self, R=None):
        var_p = 1.
        ell_p = self.lengthscale_periodic
        a = self.b_fmK_2igrid * ell_p ** (-2. * self.igrid) * np.exp(-1. / ell_p ** 2.) * var_p
        q2 = np.sum(a, axis=0)
        # The angular frequency
        omega = 2 * np.pi / self.period
        # The model
        F_p = np.kron(np.diag(np.arange(self.order + 1)), np.array([[0., -omega], [omega, 0.]]))
        L_p = np.eye(2 * (self.order + 1))
        # Qc_p = np.zeros(2 * (self.N + 1))
        Pinf_p = np.kron(np.diag(q2), np.eye(2))
        H_p = np.kron(np.ones([1, self.order + 1]), np.array([1., 0.]))
        F_m = np.array([[-1.0 / self.lengthscale_matern]])
        L_m = np.array([[1.0]])
        Qc_m = np.array([[2.0 * self.variance / self.lengthscale_matern]])
        H_m = np.array([[1.0]])
        Pinf_m = np.array([[self.variance]])
        F = np.kron(F_m, np.eye(2 * (self.order + 1))) + np.kron(np.eye(1), F_p)
        L = np.kron(L_m, L_p)
        Qc = np.kron(Qc_m, Pinf_p)
        H = np.kron(H_m, H_p)
        # Pinf = np.kron(Pinf_m, Pinf_p)
        Pinf = block_diag(
            np.kron(Pinf_m, q2[0] * np.eye(2)),
            np.kron(Pinf_m, q2[1] * np.eye(2)),
            np.kron(Pinf_m, q2[2] * np.eye(2)),
            np.kron(Pinf_m, q2[3] * np.eye(2)),
            np.kron(Pinf_m, q2[4] * np.eye(2)),
            np.kron(Pinf_m, q2[5] * np.eye(2)),
            np.kron(Pinf_m, q2[6] * np.eye(2)),
        )
        return F, L, Qc, H, Pinf

    def stationary_covariance(self):
        var_p = 1.
        ell_p = self.lengthscale_periodic
        a = self.b_fmK_2igrid * ell_p ** (-2. * self.igrid) * np.exp(-1. / ell_p ** 2.) * var_p
        q2 = np.sum(a, axis=0)
        Pinf_m = np.array([[self.variance]])
        Pinf = block_diag(
            np.kron(Pinf_m, q2[0] * np.eye(2)),
            np.kron(Pinf_m, q2[1] * np.eye(2)),
            np.kron(Pinf_m, q2[2] * np.eye(2)),
            np.kron(Pinf_m, q2[3] * np.eye(2)),
            np.kron(Pinf_m, q2[4] * np.eye(2)),
            np.kron(Pinf_m, q2[5] * np.eye(2)),
            np.kron(Pinf_m, q2[6] * np.eye(2)),
        )
        return Pinf

    def measurement_model(self):
        H_p = np.kron(np.ones([1, self.order + 1]), np.array([1., 0.]))
        H_m = np.array([[1.0]])
        H = np.kron(H_m, H_p)
        return H

    def state_transition(self, dt):
        """
        Calculation of the closed form discrete-time state
        transition matrix A = expm(F??t) for the Quasi-Periodic Matern-3/2 prior
        :param dt: step size(s), ??t = t??? - t????????? [M+1, 1]
        :return: state transition matrix A [M+1, D, D]
        """
        # The angular frequency
        omega = 2 * np.pi / self.period
        harmonics = np.arange(self.order + 1) * omega
        R0 = rotation_matrix(dt, harmonics[0])
        R1 = rotation_matrix(dt, harmonics[1])
        R2 = rotation_matrix(dt, harmonics[2])
        R3 = rotation_matrix(dt, harmonics[3])
        R4 = rotation_matrix(dt, harmonics[4])
        R5 = rotation_matrix(dt, harmonics[5])
        R6 = rotation_matrix(dt, harmonics[6])
        A = np.exp(-dt / self.lengthscale_matern) * block_diag(R0, R1, R2, R3, R4, R5, R6)
        return A


class QuasiPeriodicMatern32(Kernel):
    """
    Quasi-periodic kernel in SDE form (product of Periodic and Matern-3/2).
    Hyperparameters:
        variance, ????
        lengthscale of Periodic, l_p
        period, p
        lengthscale of Matern, l_m
    The associated continuous-time state space model matrices are constructed via
    a sum of cosines times a Matern-3/2.
    """
    def __init__(self, variance=1.0, lengthscale_periodic=1.0, period=1.0, lengthscale_matern=1.0, order=6):
        self.transformed_lengthscale_periodic = objax.TrainVar(np.array(softplus_inv(lengthscale_periodic)))
        self.transformed_variance = objax.TrainVar(np.array(softplus_inv(variance)))
        self.transformed_period = objax.TrainVar(np.array(softplus_inv(period)))
        self.transformed_lengthscale_matern = objax.TrainVar(np.array(softplus_inv(lengthscale_matern)))
        super().__init__()
        self.name = 'Quasi-periodic Matern-3/2'
        self.order = order
        self.igrid = np.meshgrid(np.arange(self.order + 1), np.arange(self.order + 1))[1]
        factorial_mesh_K = np.array([[1., 1., 1., 1., 1., 1., 1.],
                                     [1., 1., 1., 1., 1., 1., 1.],
                                     [2., 2., 2., 2., 2., 2., 2.],
                                     [6., 6., 6., 6., 6., 6., 6.],
                                     [24., 24., 24., 24., 24., 24., 24.],
                                     [120., 120., 120., 120., 120., 120., 120.],
                                     [720., 720., 720., 720., 720., 720., 720.]])
        b = np.array([[1., 0., 0., 0., 0., 0., 0.],
                      [0., 2., 0., 0., 0., 0., 0.],
                      [2., 0., 2., 0., 0., 0., 0.],
                      [0., 6., 0., 2., 0., 0., 0.],
                      [6., 0., 8., 0., 2., 0., 0.],
                      [0., 20., 0., 10., 0., 2., 0.],
                      [20., 0., 30., 0., 12., 0., 2.]])
        self.b_fmK_2igrid = b * (1. / factorial_mesh_K) * (2. ** -self.igrid)

    @property
    def variance(self):
        return softplus(self.transformed_variance.value)

    @property
    def lengthscale_periodic(self):
        return softplus(self.transformed_lengthscale_periodic.value)

    @property
    def lengthscale_matern(self):
        return softplus(self.transformed_lengthscale_matern.value)

    @property
    def period(self):
        return softplus(self.transformed_period.value)

    def K(self, X, X2):
        raise NotImplementedError

    def kernel_to_state_space(self, R=None):
        var_p = 1.
        ell_p = self.lengthscale_periodic
        a = self.b_fmK_2igrid * ell_p ** (-2. * self.igrid) * np.exp(-1. / ell_p ** 2.) * var_p
        q2 = np.sum(a, axis=0)
        # The angular frequency
        omega = 2 * np.pi / self.period
        # The model
        F_p = np.kron(np.diag(np.arange(self.order + 1)), np.array([[0., -omega], [omega, 0.]]))
        L_p = np.eye(2 * (self.order + 1))
        # Qc_p = np.zeros(2 * (self.N + 1))
        Pinf_p = np.kron(np.diag(q2), np.eye(2))
        H_p = np.kron(np.ones([1, self.order + 1]), np.array([1., 0.]))
        lam = 3.0 ** 0.5 / self.lengthscale_matern
        F_m = np.array([[0.0, 1.0],
                        [-lam ** 2, -2 * lam]])
        L_m = np.array([[0],
                        [1]])
        Qc_m = np.array([[12.0 * 3.0 ** 0.5 / self.lengthscale_matern ** 3.0 * self.variance]])
        H_m = np.array([[1.0, 0.0]])
        Pinf_m = np.array([[self.variance, 0.0],
                           [0.0, 3.0 * self.variance / self.lengthscale_matern ** 2.0]])
        # F = np.kron(F_p, np.eye(2)) + np.kron(np.eye(14), F_m)
        F = np.kron(F_m, np.eye(2 * (self.order + 1))) + np.kron(np.eye(2), F_p)
        L = np.kron(L_m, L_p)
        Qc = np.kron(Qc_m, Pinf_p)
        H = np.kron(H_m, H_p)
        # Pinf = np.kron(Pinf_m, Pinf_p)
        Pinf = block_diag(
            np.kron(Pinf_m, q2[0] * np.eye(2)),
            np.kron(Pinf_m, q2[1] * np.eye(2)),
            np.kron(Pinf_m, q2[2] * np.eye(2)),
            np.kron(Pinf_m, q2[3] * np.eye(2)),
            np.kron(Pinf_m, q2[4] * np.eye(2)),
            np.kron(Pinf_m, q2[5] * np.eye(2)),
            np.kron(Pinf_m, q2[6] * np.eye(2)),
        )
        return F, L, Qc, H, Pinf

    def stationary_covariance(self):
        var_p = 1.
        ell_p = self.lengthscale_periodic
        a = self.b_fmK_2igrid * ell_p ** (-2. * self.igrid) * np.exp(-1. / ell_p ** 2.) * var_p
        q2 = np.sum(a, axis=0)
        Pinf_m = np.array([[self.variance, 0.0],
                           [0.0, 3.0 * self.variance / self.lengthscale_matern ** 2.0]])
        Pinf = block_diag(
            np.kron(Pinf_m, q2[0] * np.eye(2)),
            np.kron(Pinf_m, q2[1] * np.eye(2)),
            np.kron(Pinf_m, q2[2] * np.eye(2)),
            np.kron(Pinf_m, q2[3] * np.eye(2)),
            np.kron(Pinf_m, q2[4] * np.eye(2)),
            np.kron(Pinf_m, q2[5] * np.eye(2)),
            np.kron(Pinf_m, q2[6] * np.eye(2)),
        )
        return Pinf

    def measurement_model(self):
        H_p = np.kron(np.ones([1, self.order + 1]), np.array([1., 0.]))
        H_m = np.array([[1.0, 0.0]])
        H = np.kron(H_m, H_p)
        return H

    def state_transition(self, dt):
        """
        Calculation of the closed form discrete-time state
        transition matrix A = expm(F??t) for the Quasi-Periodic Matern-3/2 prior
        :param dt: step size(s), ??t = t??? - t????????? [M+1, 1]
        :return: state transition matrix A [M+1, D, D]
        """
        lam = np.sqrt(3.0) / self.lengthscale_matern
        # The angular frequency
        omega = 2 * np.pi / self.period
        harmonics = np.arange(self.order + 1) * omega
        R0 = self.subband_mat32(dt, lam, harmonics[0])
        R1 = self.subband_mat32(dt, lam, harmonics[1])
        R2 = self.subband_mat32(dt, lam, harmonics[2])
        R3 = self.subband_mat32(dt, lam, harmonics[3])
        R4 = self.subband_mat32(dt, lam, harmonics[4])
        R5 = self.subband_mat32(dt, lam, harmonics[5])
        R6 = self.subband_mat32(dt, lam, harmonics[6])
        A = np.exp(-dt * lam) * block_diag(R0, R1, R2, R3, R4, R5, R6)
        return A

    @staticmethod
    def subband_mat32(dt, lam, omega):
        R = rotation_matrix(dt, omega)
        Ri = np.block([
            [(1. + dt * lam) * R, dt * R],
            [-dt * lam ** 2 * R,  (1. - dt * lam) * R]
        ])
        return Ri


class SubbandMatern12(Kernel):
    """
    Subband Matern-1/2 (i.e. Exponential) kernel in SDE form (product of Cosine and Matern-1/2).
    Hyperparameters:
        variance, ????
        lengthscale, l
        radial frequency, ??
    The associated continuous-time state space model matrices are constructed via
    kronecker sums and products of the exponential and cosine components:
    F      = F_exp ??? F_cos  =  ( -1/l  -??
                                 ??     -1/l )
    L      = L_exp ??? I      =  ( 1      0
                                 0      1 )
    Qc     = I ??? Qc_exp     =  ( 2????/l  0
                                 0      2????/l )
    H      = H_exp ??? H_cos  =  ( 1      0 )
    Pinf   = Pinf_exp ??? I   =  ( ????     0
                                 0      ???? )
    and the discrete-time transition matrix is (for step size ??t),
    A      = exp(-??t/l) ( cos(????t)   -sin(????t)
                          sin(????t)    cos(????t) )
    """
    def __init__(self, variance=1.0, lengthscale=1.0, radial_frequency=1.0, fix_variance=False):
        self.transformed_lengthscale = objax.TrainVar(np.array(softplus_inv(lengthscale)))
        if fix_variance:
            self.transformed_variance = objax.StateVar(np.array(softplus_inv(variance)))
        else:
            self.transformed_variance = objax.TrainVar(np.array(softplus_inv(variance)))
        self.transformed_radial_frequency = objax.TrainVar(np.array(softplus_inv(radial_frequency)))
        super().__init__()
        self.name = 'Subband Matern-1/2'

    @property
    def variance(self):
        return softplus(self.transformed_variance.value)

    @property
    def lengthscale(self):
        return softplus(self.transformed_lengthscale.value)

    @property
    def radial_frequency(self):
        return softplus(self.transformed_radial_frequency.value)

    def K(self, X, X2):
        raise NotImplementedError

    def kernel_to_state_space(self, R=None):
        F_mat = np.array([[-1.0 / self.lengthscale]])
        L_mat = np.array([[1.0]])
        Qc_mat = np.array([[2.0 * self.variance / self.lengthscale]])
        H_mat = np.array([[1.0]])
        Pinf_mat = np.array([[self.variance]])
        F_cos = np.array([[0.0, -self.radial_frequency],
                          [self.radial_frequency, 0.0]])
        H_cos = np.array([[1.0, 0.0]])
        # F = (-1/l -??
        #      ??    -1/l)
        F = np.kron(F_mat, np.eye(2)) + F_cos
        L = np.kron(L_mat, np.eye(2))
        Qc = np.kron(np.eye(2), Qc_mat)
        H = np.kron(H_mat, H_cos)
        Pinf = np.kron(Pinf_mat, np.eye(2))
        return F, L, Qc, H, Pinf

    def stationary_covariance(self):
        Pinf_mat = np.array([[self.variance]])
        Pinf = np.kron(Pinf_mat, np.eye(2))
        return Pinf

    def measurement_model(self):
        H_mat = np.array([[1.0]])
        H_cos = np.array([[1.0, 0.0]])
        H = np.kron(H_mat, H_cos)
        return H

    def state_transition(self, dt):
        """
        Calculation of the closed form discrete-time state
        transition matrix A = expm(F??t) for the Subband Matern-1/2 prior:
        A = exp(-??t/l) ( cos(????t)   -sin(????t)
                         sin(????t)    cos(????t) )
        :param dt: step size(s), ??t = t??? - t????????? [1]
        :return: state transition matrix A [2, 2]
        """
        R = rotation_matrix(dt, self.radial_frequency)
        A = np.exp(-dt / self.lengthscale) * R  # [2, 2]
        return A


class Independent(Kernel):
    """
    A stack of independent GP priors. 'kernels' is a list of GP kernels, and this class stacks
    the state space models such that each component is fed to the likelihood.
    This class differs from Sum only in the measurement model.
    """
    def __init__(self, kernels):
        self.num_kernels = len(kernels)
        for i in range(self.num_kernels):
            selfdotkerneli = "self.kernel" + str(i)
            exec(selfdotkerneli + " = kernels[i]")
        self.name = 'Independent'

    def K(self, X, X2):
        Kstack = [self.kernel0.K(X, X2)]
        for i in range(1, self.num_kernels):
            kerneli = eval("self.kernel" + str(i))
            Kstack = Kstack + [kerneli.K(X, X2)]
        return Kstack

    def kernel_to_state_space(self, R=None):
        F, L, Qc, H, Pinf = self.kernel0.kernel_to_state_space(R)
        for i in range(1, self.num_kernels):
            kerneli = eval("self.kernel" + str(i))
            F_, L_, Qc_, H_, Pinf_ = kerneli.kernel_to_state_space(R)
            F = block_diag(F, F_)
            L = block_diag(L, L_)
            Qc = block_diag(Qc, Qc_)
            H = block_diag(H, H_)
            Pinf = block_diag(Pinf, Pinf_)
        return F, L, Qc, H, Pinf

    def measurement_model(self):
        H = self.kernel0.measurement_model()
        for i in range(1, self.num_kernels):
            kerneli = eval("self.kernel" + str(i))
            H_ = kerneli.measurement_model()
            H = block_diag(H, H_)
        return H

    def stationary_covariance(self):
        Pinf = self.kernel0.stationary_covariance()
        for i in range(1, self.num_kernels):
            kerneli = eval("self.kernel" + str(i))
            Pinf_ = kerneli.stationary_covariance()
            Pinf = block_diag(Pinf, Pinf_)
        return Pinf

    def inducing_precision(self):
        Qzz0, Lzz0 = self.kernel0.inducing_precision()
        Qzz, Lzz = [Qzz0], [Lzz0]
        for i in range(1, self.num_kernels):
            kerneli = eval("self.kernel" + str(i))
            Qzz_, Lzz_ = kerneli.inducing_precision()
            Qzz, Lzz = Qzz + [Qzz_], Lzz + [Lzz_]
        return Qzz, Lzz

    def state_transition(self, dt):
        """
        Calculation of the discrete-time state transition matrix A = expm(F??t) for a sum of GPs
        :param dt: step size(s), ??t = t??? - t????????? [1]
        :return: state transition matrix A [D, D]
        """
        A = self.kernel0.state_transition(dt)
        for i in range(1, self.num_kernels):
            kerneli = eval("self.kernel" + str(i))
            A_ = kerneli.state_transition(dt)
            A = block_diag(A, A_)
        return A


class Separate(Independent):
    pass


class Stack(Independent):
    pass


class Sum(Independent):
    """
    A sum of GP priors. 'components' is a list of GP kernels, and this class stacks
    the state space models to produce their sum.
    This class differs from Independent only in the measurement model.
    """
    def __init__(self, kernels):
        super().__init__(kernels=kernels)
        self.name = 'Sum'

    def K(self, X, X2):
        Ksum = self.kernel0.K(X, X2)
        for i in range(1, self.num_kernels):
            kerneli = eval("self.kernel" + str(i))
            Ksum = Ksum + kerneli.K(X, X2)
        return Ksum

    def kernel_to_state_space(self, R=None):
        F, L, Qc, H, Pinf = self.kernel0.kernel_to_state_space(R)
        for i in range(1, self.num_kernels):
            kerneli = eval("self.kernel" + str(i))
            F_, L_, Qc_, H_, Pinf_ = kerneli.kernel_to_state_space(R)
            F = block_diag(F, F_)
            L = block_diag(L, L_)
            Qc = block_diag(Qc, Qc_)
            H = np.block([
                H, H_
            ])
            Pinf = block_diag(Pinf, Pinf_)
        return F, L, Qc, H, Pinf

    def measurement_model(self):
        H = self.kernel0.measurement_model()
        for i in range(1, self.num_kernels):
            kerneli = eval("self.kernel" + str(i))
            H_ = kerneli.measurement_model()
            H = np.block([
                H, H_
            ])
        return H


class Separable(Independent):
    """
    A product of separable GP priors. 'components' is a list of GP kernels, and this class stacks
    the state space models to produce their product.
    This class differs from Independent only in the measurement model.
    TODO: this assumes that each kernel acts on a different dimension. Generalise.
    TODO: implement state space form of product kernels
    """
    def __init__(self, kernels):
        super().__init__(kernels=kernels)
        self.name = 'Product'

    def K(self, X, X2):
        Kprod = self.kernel0.K(X[:, :1], X2[:, :1])
        for i in range(1, self.num_kernels):
            kerneli = eval("self.kernel" + str(i))
            Kprod = Kprod * kerneli.K(X[:, i:i+1], X2[:, i:i+1])
        return Kprod

    # def measurement_model(self):
    #     H = self.kernel0.measurement_model()
    #     for i in range(1, self.num_kernels):
    #         kerneli = eval("self.kernel" + str(i))
    #         H_ = kerneli.measurement_model()
    #         H = np.block([
    #             H, H_
    #         ])
    #     return H


class SpectroTemporal(Independent):

    def __init__(self,
                 subband_lengthscales,
                 subband_frequencies,
                 modulator_variances,
                 modulator_lengthscales,
                 subband_kernel=SubbandMatern12,
                 modulator_kernel=Matern32):
        assert len(subband_lengthscales) == len(subband_frequencies)
        assert len(modulator_lengthscales) == len(modulator_variances)
        num_subbands = len(subband_frequencies)
        num_modulators = len(modulator_lengthscales)
        radial_freq = 2 * np.pi * subband_frequencies  # radial freq = 2pi * f
        kernels = [subband_kernel(variance=1, lengthscale=subband_lengthscales[0], radial_frequency=radial_freq[0],
                                  fix_variance=True)]
        for i in range(1, num_subbands):
            kernels.append(
                subband_kernel(variance=1, lengthscale=subband_lengthscales[i], radial_frequency=radial_freq[i],
                               fix_variance=True)
            )
        for j in range(num_modulators):
            kernels.append(
                modulator_kernel(variance=modulator_variances[j], lengthscale=modulator_lengthscales[j])
            )
        super().__init__(kernels=kernels)
