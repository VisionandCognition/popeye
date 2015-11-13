import os
import multiprocessing
from itertools import repeat
import ctypes

import numpy as np
import numpy.testing as npt
import nose.tools as nt
from scipy.signal import fftconvolve

import popeye.utilities as utils
import popeye.css as css
from popeye.visual_stimulus import VisualStimulus, simulate_bar_stimulus, resample_stimulus

def test_css_fit():
    
    # stimulus features
    viewing_distance = 38
    screen_width = 25
    thetas = np.arange(0,360,90)
    num_blank_steps = 30
    num_bar_steps = 30
    ecc = 12
    tr_length = 1.0
    frames_per_tr = 1.0
    scale_factor = 0.20
    resample_factor = 0.25
    pixels_across = 800 * resample_factor
    pixels_down = 600 * resample_factor
    dtype = ctypes.c_int16
    
    # create the sweeping bar stimulus in memory
    bar = simulate_bar_stimulus(pixels_across, pixels_down, viewing_distance, 
                                screen_width, thetas, num_bar_steps, num_blank_steps, ecc)
    
    # create an instance of the Stimulus class
    stimulus = VisualStimulus(bar, viewing_distance, screen_width, scale_factor, tr_length, dtype)
    
    # initialize the gaussian model
    model = css.CompressiveSpatialSummationModel(stimulus, utils.double_gamma_hrf)
    
    # generate a random pRF estimate
    x = -5.24
    y = 2.58
    sigma = 1.24
    hrf_delay = -0.25
    beta = 1
    n = 0.33
    
    # create the "data"
    data =  model.generate_prediction(x, y, sigma, n, beta, hrf_delay)
    
    # set search grid
    x_grid = (-10,10)
    y_grid = (-10,10)
    s_grid = (1/stimulus.ppd,5.25)
    n_grid = (0.1,0.5)
    b_grid = (0.01,5)
    h_grid = (-4.0,4.0)
    
    # set search bounds
    x_bound = (-12.0,12.0)
    y_bound = (-12.0,12.0)
    s_bound = (1/stimulus.ppd,12.0)
    n_bound = (1e-8,1.0)
    b_bound = (1e-8,1e5)
    h_bound = (-5.0,5.0)
    
    # loop over each voxel and set up a GaussianFit object
    grids = (x_grid, y_grid, s_grid, n_grid, b_grid, h_grid)
    bounds = (x_bound, y_bound, s_bound, n_bound, b_bound, h_bound)
    
    # set some meta data
    Ns = 3
    voxel_index = (1,2,3)
    auto_fit = True
    verbose = 0
    
    # fit the response
    fit = css.CompressiveSpatialSummationFit(model, data, grids, bounds, Ns, voxel_index, auto_fit, verbose)
    
    # assert equivalence
    nt.assert_almost_equal(fit.x, x)
    nt.assert_almost_equal(fit.y, y)
    nt.assert_almost_equal(fit.sigma, sigma)
    nt.assert_almost_equal(fit.hrf_delay, hrf_delay)
    nt.assert_almost_equal(fit.beta, beta)
    # nt.assert_almost_equal(fit.n, n)