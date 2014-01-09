from __future__ import division
import time
import shutil

import numpy as np
from scipy.special import gamma
from scipy.optimize import fmin_powell, fmin, brute
from scipy.stats import linregress

from popeye.spinach import MakeFastPrediction
import popeye.utilities as utils

def double_gamma_hrf(delay):
    """
    The double-gamma hemodynamic reponse function (HRF) used to convolve with
    the stimulus time-series.
    
    The user specifies only the delay of the peak and under-shoot The delay
    shifts the peak and under-shoot by a variable number of seconds.  The other
    parameters are hard-coded.  The HRF delay is modeled for each voxel
    independently.  The double-gamme HRF andhard-coded values are based on
    previous work (Glover, 1999).
    
    
    Parameters
    ----------
    delay : int
        The delay of the HRF peak and under-shoot.
        
        
    Returns
    -------
    hrf : ndarray
        The hemodynamic response function to convolve with the stimulus
        time-series.
    
    
    Reference
    ----------
    Glover, G.H. (1999) Deconvolution of impulse response in event-related BOLD.
    fMRI. NeuroImage 9: 416 429.
    
    """
    
    # add delay to the peak and undershoot params (alpha 1 and 2)
    alpha_1 = 5.0+delay
    beta_1 = 1.0
    c = 0.2
    alpha_2 = 15.0+delay
    beta_2 = 1.0
    
    t = np.arange(0,33)
    scale = 1
    hrf = scale*( ( ( t ** (alpha_1 - 1 ) * beta_1 ** alpha_1 *
                      np.exp( -beta_1 * t )) /gamma( alpha_1 )) - c *
        ( ( t ** (alpha_2 - 1 ) * beta_2 ** alpha_2 * np.exp( -beta_2 * t ))
          /gamma( alpha_2 ) ) )
            
    return hrf

def error_function(modelParams,ts_actual,degX,degY,stimArray):
    """
    The objective function that yields a minimizeable error between the
    predicted and actual BOLD time-series.
    
    The objective function takes candidate pRF estimates `modelParams`,
    including a parameter for the screen location (x,y) and dispersion (sigma)
    of the 2D Gaussian as well as the HRF delay (tau).  The objective function
    also takes the ancillary parameters `degX` and `degY`, visual coordinate
    arrays, as well as the digitized stimulus array `stimArray`.  The predicted
    time-series is generated by multiplying the pRF by the stimulus array and
    convolving the result with the double-gamma HRF.  The predicted time-series
    is mean centered and variance normalized.  The residual sum of squared
    errors is computed between the predicted and actual time-series and
    returned.
    
    This function makes use of the Cython optimising static compiler.
    MakeFastPrediction is written in Cython and computes the pre HRF convolved
    model time-series.
    
    Parameters
    ----------
    modelParams : ndarray, dtype=single/double
        A quadruplet model parameters including the pRF estimate (x,y,sigma)
        and the HRF delay (tau).

    ts_actual : ndarray
        A vector of the actual BOLD time-series extacted from a single voxel
        coordinate.

    degX : ndarray
        An array representing the horizontal extent of the visual display in
        terms of degrees of visual angle.

    degY : ndarray
        An array representing the vertical extent of the visual display in
        terms of degrees of visual angle.  stimArray : ndarray Array_like means
        all those objects -- lists, nested lists, etc. -- that can be converted
        to an array.
        
    Returns
    -------
    error : float
        The residual sum of squared errors computed between the predicted and
        actual time-series.    
    """
    # if the x or y are off the screen, abort with an inf
    if np.abs(modelParams[0]) > np.floor(np.max(degY))-1:
        return np.inf
    if np.abs(modelParams[1]) > np.floor(np.max(degY))-1:
        return np.inf
        
    # if the sigma is larger than the screen width, abort with an inf
    if np.abs(modelParams[2]) > np.floor(np.max(degY))-1:
        return np.inf
    
    # if the sigma is <= 0, abort with an inf
    if modelParams[2] <= 0:
        return np.inf
        
    # if the HRF delay parameter is greater than 4 seconds, abort with an inf
    if np.abs(modelParams[3]) > 4:
        return np.inf
        
    # otherwise generate a prediction
    ts_stim = MakeFastPrediction(degX,
                                degY,
                                stimArray,
                                modelParams[0],
                                modelParams[1],
                                modelParams[2])
    
    # compute the double-gamma HRF at the specified delay
    hrf = double_gamma_hrf(modelParams[3])
    
    # convolve the stimulus time-series with the HRF
    ts_model= np.convolve(ts_stim, hrf)
    ts_model= ts_model[0:len(ts_actual)]
    
    # z-score the model time-series
    ts_model-= np.mean(ts_model)
    ts_model/= np.std(ts_model)
    
    # compute the RSS
    error = np.sum((ts_model-ts_actual)**2)
    
    # catch NaN
    if np.isnan(np.sum(error)):
        return np.inf
    
    return error


def adaptive_brute_force_grid_search(bounds,epsilon,rounds,ts_actual,degX,degY,
                                     stimArray):
    """    
    An adaptive brute force grid-search to generate a ball-park pRF estimate for
    fine tuning via a gradient descent error minimization.

    
    The adaptive brute-force grid-search sparsely samples the parameter space
    and uses a down-sampled version of the stimulus and cooridnate matrices.
    This is intended to yield an initial, ball-park solution that is then fed
    into the more finely-tuned fmin_powell in the compute_prf_estimate method
    below. 
    
    Parameters
    ----------
    bounds : tuple
        A tuple of paired tuples for the upper and lower bounds of the model
        parameters  e.g. ((-10,10),(-10,10),((0.25,5.25),(-4,4))
    epsilon : int
        The step-size for reducing the grid-search bounds on each iteration
        through the adaptive brute-force search. 
    rounds : int
        The number of iterations through the adaptive brute-force search
    ts_actual : ndarray
        A vector of the actual BOLD time-series extacted from a single voxel
        coordinate.
    degX : ndarray
        An array representing the horizontal extent of the visual display in
        terms of degrees of visual angle.
    degY : ndarray
        An array representing the vertical extent of the visual display in
        terms of degrees of visual angle.
    stimArray : ndarray
        Array_like means all those objects -- lists, nested lists, etc. --
        that can be converted to an array.
        
    Returns
    -------
    error : float
        The residual sum of squared errors computed between the predicted and
        actual time-series. 
    
    """
    
    # set initial pass to 1
    passNum = 1
    
    # make as many passes as the user specifies in rounds
    while passNum <= rounds:
        
        # get a fit estimate by sparsely sampling the 4-parameter space
        phat = brute(error_function,
                 args=(ts_actual, degX, degY, stimArray),
                 ranges=bounds,
                 Ns=5,
                 finish=fmin_powell)
        
        # recompute the grid-search bounds by halving the sampling space
        epsilon /= 2.0
        bounds = ((phat[0]-epsilon,phat[0]+epsilon),
                  (phat[1]-epsilon,phat[1]+epsilon),
                  (phat[2]-epsilon,phat[2]+epsilon),
                  (phat[3]-epsilon,phat[3]+epsilon))
        
        # iterate the pass variable
        passNum += 1
    
    return phat

def compute_prf_estimate(deg_x_coarse, deg_y_coarse, deg_x_fine, deg_y_fine,
                         stim_arr_coarse, stim_arr_fine, funcData, 
                         core_voxels, results_q, bounds=(), uncorrected_rval=0, 
                         norm_func=utils.zscore, verbose=True):
    """ 
    The main pRF estimation method using a single Gaussian pRF model (Dumoulin
    & Wandell, 2008). 
    
    The function takes voxel coordinates, `voxels`, and uses a combination of
    the adaptive brute force grid-search and a gradient descent error
    minimization to compute the pRF estimate and HRF delay.  An initial guess
    of the pRF estimate is computed via the adaptive brute force grid-search is
    computed and handed to scipy.opitmize.fmin_powell for fine tuning.  Once
    the error minimization routine converges on a solution, fit statistics are
    computed via scipy.stats.linregress.  The output are stored in the
    multiprocessing.Queue object `results_q` and returned once all the voxels
    specified in `voxels` have been estimated.
    
    Parameters
    ----------
    deg_x_coarse : XXX
    deg_y_coarse : XXX
    deg_x_fine : XXX
    deg_y_fine : XXX
    stim_arr_coarse : XXX
    stim_arr_fine : XXX
    funcData : ndarray
        A 4D numpy array containing the functional data to be used for the pRF
        estimation. For details, see config.py
    bounds : XXX
    core_voxels : XXX
    uncorrected_rval : XXX 
    results_q : multiprocessing.Queue object
        A multiprocessing.Queue object into which list of pRF estimates and fit
        metrics are stacked. 
    norm_func : callable, optional
        The function used to normalize the time-series data. Can be any
        function that takes an array as input and returns a same-shaped array,
    but consider using `utils.percent_change` or `utils.zscore` (the default).
    verbose : bool, optional
        Toggle the progress printing to the terminal.

    Returns
    -------
    results_q : multiprocessing.Queue
        The pRF four parameter estimate for each voxel in addition to
        statistics for evaluating the goodness of fit. 
    
    Reference
    ----------
    Glover, G.H. (1999) Deconvolution of impulse response in event-related BOLD.
    fMRI. NeuroImage 9: 416 429.

    Dumoulin S.O and Wandell B.A. (2008). Population receptive field estimates
    in human visual cortex. Neuroimage 39: 647-660.
    
    """
    # grab voxel indices
    xi,yi,zi = core_voxels
    
    # initialize a list in which to store the results
    results = []
    
    # printing niceties
    numVoxels = len(xi)
    voxelCount = 1
    printLength = len(xi)/10
    
    # main loop
    for xvoxel, yvoxel, zvoxel in zip(xi, yi, zi):
        
        # time each voxel's estimation time
        tic = time.clock()

        # Grab the 1-D timeseries for this voxel
        ts_actual = funcData[xvoxel, yvoxel, zvoxel,:]
        ts_actual = norm_func(ts_actual)
        
        # make sure we're only analyzing valid voxels
        if not np.isnan(np.sum(ts_actual)):
            x, y, s, d, err, stats = voxel_prf(ts_actual,
                                               deg_x_coarse,
                                               deg_y_coarse,
                                               deg_x_fine,
                                               deg_y_fine,
                                               stim_arr_coarse,
                                               stim_arr_fine,
                                               bounds=bounds,
                                               uncorrected_rval=0,
                                               norm_func=norm_func)
    
            # close the processing time
            toc = time.clock()
                                    
            if verbose:
                  percentDone = (voxelCount / numVoxels) * 100
                  # print the details of the estimation for this voxel
                  report_str = "%.01f%% DONE "%percentDone
                  report_str += "VOXEL=(%.03d,%.03d,%.03d) "%(xvoxel,
                                                              yvoxel,
                                                              zvoxel)
                  report_str += "TIME=%.03f "%toc-tic
                  report_str += "ERROR=%.03d "%err
                  report_str += "RVAL=%.02f"%stats[2]
                  print(report_str)
                  # store the results
            results.append((xvoxel, yvoxel, zvoxel, x, y, s, d, stats))
                
            # interate variable
            voxelCount += 1

    # add results to the queue
    results_q.put(results)
    return results_q


def voxel_prf(ts_vox, deg_x_coarse, deg_y_coarse,
              deg_x_fine, deg_y_fine, stim_arr_coarse,
              stim_arr_fine, bounds=(), uncorrected_rval=0,
              norm_func=utils.zscore):
      """
      Compute the pRF parameters for a single voxel.
      
      Start with a brute force grid search, at coarse resolution and follow up
      with a gradient descent at fine resolution.
      
      Parameters
      ----------
      ts_vox : 1D array
         The normalized time-series of a
      deg_x_coarse, deg_y_coarse :
      deg_x_fine, deg_y_fine :
      stim_arr_coarse :
      stim_arr_fine :
      uncorrected_rval : float, optional
      norm_func: callable, optional
      
      Returns
      -------
      The pRF parameters for this voxel
      x : 
      y : 
      sigma : 
      hrf_delay: 
      stats: 
      
      """
      
      # compute the initial guess with the adaptive brute-force grid-search
      x0, y0, s0, hrf0 = adaptive_brute_force_grid_search(bounds,
                                                          1,
                                                          3,
                                                          ts_vox,
                                                          deg_x_coarse,
                                                          deg_y_coarse,
                                                          stim_arr_coarse)
                                                          
      # regenerate the best-fit for computing the threshold
      ts_stim = MakeFastPrediction(deg_x_coarse,
                                   deg_y_coarse,
                                   stim_arr_coarse,
                                   x0,
                                   y0,
                                   s0)
                                   
      # convolve with HRF and z-score
      hrf = double_gamma_hrf(hrf0)
      ts_model= np.convolve(ts_stim, hrf)
      ts_model= ts_model[0:len(ts_vox)]
      ts_model= norm_func(ts_model)
      
      # compute the p-value to be used for thresholding
      stats0 = linregress(ts_vox, ts_model)
      
      # only continue if the brute-force grid-search came close to a
      # solution 
      if stats0[2] > uncorrected_rval:
          # gradient-descent the solution using the x0 from the
          [x, y, sigma, hrf_delay], err,  _, _, _, warnflag =\
              fmin_powell(error_function,
                          (x0, y0, s0, hrf0),
                          args=(ts_vox,
                                deg_x_fine,
                                deg_y_fine,
                                stim_arr_fine),
                                full_output=True,
                                disp=False)
                                
          # ensure that the fmin finished OK:
          if (warnflag == 0 and not np.any(np.isnan([x, y, sigma, hrf_delay]))
             and not np.isinf(err)):
             
              # regenerate the best-fit for computing the threshold
              ts_stim = MakeFastPrediction(deg_x_fine,
                                          deg_y_fine,
                                          stim_arr_fine,
                                          x,
                                          y,
                                          sigma)
                                          
              # convolve with HRF and z-score
              hrf = double_gamma_hrf(hrf_delay)
              ts_model= np.convolve(ts_stim, hrf)
              ts_model= ts_model[0:len(ts_vox)]
              ts_model = norm_func(ts_model)
              
              # compute the final stats:
              stats = linregress(ts_vox, ts_model)
              
              return x, y, sigma, hrf_delay, err, stats
          else:
              print("The fmin did not finish properly!")
              return None
      else:
         print("The brute-force did not produce a fit better than an r-value of %.02f!" %(uncorrected_rval))
         return None
