import logging
import operator
import warnings

import lavaburst
import cooltools.insulation
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


def calc_mean_tad_size(boundaries, filters, ch, mis, mts, wind, resolution):
    """
    Function to calculate some statistics: mean tad size, total coverage, mean insulation score.
    This function uses only in insulation method!
    :param boundaries: boundaries dataframe.
    :param filters: regions of Hi-C map that should be ignored (white stripes).
    :param ch: chromosome name.
    :param mis: maximum intertad size for your method.
    :param mts: maximum TAD size.
    :param wind: single window value.
    :param resolution: Hi-C resolution of your coolfiles.
    :return: mean tad size, total chromosome coverage and mean insulation for certain window value
    """
    select_tads = pd.DataFrame(index=list(range(boundaries.shape[0] - 1)),
                               columns=['left_start', 'left_end', 'right_start', 'right_end', 'left_insulation',
                                        'right_insulation', 'left_boundary_strength', 'right_boundary_strength',
                                        'length', 'is_normal'])
    select_tads['left_start'] = list(boundaries.iloc[:-1]['start'])
    select_tads['left_end'] = list(boundaries.iloc[:-1]['end'])
    select_tads['right_start'] = list(boundaries.iloc[1:]['start'])
    select_tads['right_end'] = list(boundaries.iloc[1:]['end'])
    select_tads['left_insulation'] = list(boundaries.iloc[:-1]['log2_insulation_score_{}'.format(int(wind))])
    select_tads['right_insulation'] = list(boundaries.iloc[1:]['log2_insulation_score_{}'.format(int(wind))])
    select_tads['left_boundary_strength'] = list(boundaries.iloc[:-1]['boundary_strength_{}'.format(int(wind))])
    select_tads['right_boundary_strength'] = list(boundaries.iloc[1:]['boundary_strength_{}'.format(int(wind))])
    select_tads['length'] = list((select_tads['right_start'] - select_tads['left_end']) / resolution)

    try:
        full_ins = list(select_tads['left_insulation']) + [list(select_tads['right_insulation'])[-1]]
    except Exception as e:
        full_ins = []
    try:
        full_bsc = list(select_tads['left_boundary_strength']) + [list(select_tads['right_boundary_strength'])[-1]]
    except Exception as e:
        full_bsc = []

    select_tads = select_tads[(select_tads['length'] > mis) & (select_tads['length'] < mts)]
    select_tads['is_normal'] = list(map(
        lambda x, y: True if filters[ch][(filters[ch][:, 0] >= x) & (filters[ch][:, 1] <= y)].shape[0] == 0 else False,
        select_tads['left_end'], select_tads['right_start']))
    select_tads = select_tads[select_tads['is_normal'] == True]

    mean_tad = np.mean(select_tads['length'])
    try:
        mean_ins = np.mean(list(select_tads['left_insulation']) + [list(select_tads['right_insulation'])[-1]])
    except Exception as e:
        mean_ins = np.nan
    try:
        mean_bsc = np.mean(list(select_tads['left_boundary_strength']) + [list(select_tads['right_boundary_strength'])[-1]])
    except Exception as e:
        mean_bsc = np.nan
    sum_cov = np.sum(select_tads['length'])

    if np.isnan(mean_tad): mean_tad = 0
    if np.isnan(sum_cov): sum_cov = 0
    if np.isnan(mean_ins): mean_ins = 0
    if np.isnan(mean_bsc): mean_bsc = 0

    return mean_tad, sum_cov, mean_ins, mean_bsc, full_ins, full_bsc


def produce_boundaries_segmentation(clr, mtx, filters, window, ch, method, resolution=5000, k=3, final=False):
    """
    Function produces single segmentation (TADs boundaries calling) of mtx with one window with the algorithm provided.
    :param clr: cooler file which corresponds to single stage of development (by which we search segmentation).
    :param mtx: input numpy matrix of Hi-C contacts.
    :param filters: regions of Hi-C map that should be ignored (white stripes).
    :param window: single window value.
    :param ch: chromosome name.
    :param resolution: Hi-C resolution of your coolfiles.
    :param final: bool parameter - does iteration of optimal gamma search is final?
    :return: boundaries_coords -- 2D numpy array where boundaries_coords[:, 0] are boundaries starts and
    boundaries_coords[:, 1] are boundaries end, each row corresponding to one boundary;
    boundaries -- corresponding dataframe.
    """
    ins_scores = cooltools.insulation.calculate_insulation_score(clr, int(window), ignore_diags=2, chromosomes=[ch])
    boundaries = cooltools.insulation.find_boundaries(ins_scores, min_dist_bad_bin=k)
    #boundaries = cooltools.insulation._find_insulating_boundaries_dense(clr, int(window), min_dist_bad_bin=k, ignore_diags=2, chromosomes=[ch])
    boundaries = boundaries[
        (boundaries['boundary_strength_{}'.format(int(window))].notnull())]
    boundaries.index = list(range(boundaries.shape[0]))
    boundaries_coords = np.asarray(boundaries[['start', 'end']])

    metric_values = np.array([calc_noisy_metric(x, filters, ch, method, resolution, k) for x in boundaries_coords])
    thresh = 0

    # hist_arr = np.array(sorted(metric_values))
    # hist_arr = hist_arr[hist_arr > 0]

    # try:
    #     noise_freq = np.sum(filters[ch][:, 1] - filters[ch][:, 0]) / (mtx.shape[0] * resolution)
    #     if final: logging.info('PRODUCE_BOUNDARIES_SEGMENTATION| Noise frequency for {} opt window: {}'.format(int(window),
    #                                                                                                      noise_freq))
    #     thresh = (hist_arr[:int(len(hist_arr) * noise_freq)][-1] + hist_arr[int(len(hist_arr) * noise_freq)]) / 2
    #     if final: logging.info('PRODUCE_BOUNDARIES_SEGMENTATION| For {} opt window delete {} boundaries out of {}.'.format(
    #         int(window), boundaries_coords.shape[0] - boundaries_coords[metric_values > thresh].shape[0],
    #         boundaries_coords.shape[0]))
    #     return boundaries_coords[metric_values > thresh], boundaries[metric_values > thresh]
    # except Exception as e:
    #     return boundaries_coords, boundaries

    if final:
        logging.info('PRODUCE_BOUNDARIES_SEGMENTATION| For {} opt window delete {} boundaries out of {}.'.format(
             int(window), boundaries_coords.shape[0] - boundaries_coords[metric_values > thresh].shape[0],
             boundaries_coords.shape[0]))

    return boundaries_coords[metric_values > thresh], boundaries[metric_values > thresh]


def produce_tads_segmentation(mtx, filters, gamma, ch, good_bins='default', method='armatus', max_intertad_size=3,
                         max_tad_size=1000, final=False):
    """
    Function produces single segmentation (TADs calling) of mtx with one gamma with the algorithm provided.
    :param mtx: input numpy matrix of Hi-C contacts.
    :param filters: regions of Hi-C map that should be ignored (white stripes).
    :param gamma: single gamma value.
    :param ch: chromosome name.
    :param good_bins: bool mask of good bins.
    :param method: armatus or modularity to produce segmentation.
    :param max_intertad_size: maximum intertad size for your method.
    :param max_tad_size: maximum TAD size.
    :param final: bool parameter - does iteration of optimal gamma search is final?
    :return: 2D numpy array where segments[:,0] are segment starts and segments[:,1] are segments end,
    each row corresponding to one segment.
    """
    if np.any(np.isnan(mtx)):
        logging.warning("PRODUCE_TADS_SEGMENTATION| NaNs in dataset, please remove them first.")

    if np.diagonal(mtx).sum() > 0:
        logging.warning(
            "PRODUCE_TADS_SEGMENTATION| Note that diagonal is not removed. you might want to delete it to avoid "
            "noisy and not stable results.")

    if method == 'modularity':
        score = lavaburst.scoring.modularity_score
    elif method == 'armatus':
        score = lavaburst.scoring.armatus_score
    else:
        return

    if good_bins == 'default':
        good_bins = mtx.astype(bool).sum(axis=0) > 0

    S = score(mtx, gamma=gamma, binmask=good_bins)
    model = lavaburst.model.SegModel(S)

    segments = model.optimal_segmentation()
    v = segments[:, 1] - segments[:, 0]
    mask = (v > max_intertad_size) & (np.isfinite(v)) & (v < max_tad_size)
    segments = segments[mask]

    metric_values = np.array([calc_noisy_metric(x, filters, ch, method, resolution=0, k=0) for x in segments])
    hist_arr = np.array(sorted(metric_values))
    hist_arr = hist_arr[hist_arr > 0]
    try:
        noise_freq = np.sum(filters[ch][:, 1] - filters[ch][:, 0] + 1) / mtx.shape[0]
        if final:
            logging.info("PRODUCE_TADS_SEGMENTATION| Noise frequency in Hi-C contact matrix is {}".format(noise_freq))
        thresh = (hist_arr[:int(len(hist_arr) * noise_freq)][-1] + hist_arr[int(len(hist_arr) * noise_freq)]) / 2
        if final:
            logging.info("PRODUCE_TADS_SEGMENTATION| Finally delete {} noisy TADs out of {} from our "
                         "segmentation".format(
                segments.shape[0] - segments[metric_values > thresh].shape[0], segments.shape[0]))
        return segments[metric_values > thresh]
    except Exception as e:
        return segments


def whether_to_expand(mtx, filters, grid, ch, good_bins, method, mis, mts, start_step):
    """
    Function to check whether we could expand given grid.
    :param mtx: input numpy matrix of Hi-C contacts.
    :param filters: regions of Hi-C map that should be ignored (white stripes).
    :param grid: grid of search gamma value.
    :param ch: chromosome name.
    :param good_bins: bool mask of good bins.
    :param method: armatus or modularity to produce segmentation.
    :param mis: maximum intertad size for your method.
    :param mts: maximum TAD size.
    :param start_step: start step to search optimal gamma value. It is equal to step in grid param.
    :return: nothing.
    """
    upper_check = np.arange(grid[-1] + start_step, grid[-1] + start_step * 11, start_step)
    lower_check = np.arange(grid[0] - start_step * 10, grid[0], start_step)
    if start_step != 1:
        upper_check = np.array([round(x, len(str(start_step).split('.')[1])) for x in upper_check])
        lower_check = np.array([round(x, len(str(start_step).split('.')[1])) for x in lower_check])
    len_upper_segments = []
    len_lower_segments = []

    if not any(x < 0 for x in upper_check):
        for g in upper_check:
            len_upper_segments.append(len(list(produce_tads_segmentation(mtx, filters, g, ch, good_bins=good_bins,
                                                                    method=method, max_intertad_size=mis,
                                                                    max_tad_size=mts))))
    else:
        logging.error("WHETHER_TO_EXPAND| Your grid upper bound is probably negative! Please, select positive upper bound!")
        return

    if not any(x < 0 for x in lower_check):
        for g in lower_check:
            len_upper_segments.append(len(list(produce_tads_segmentation(mtx, filters, g, ch, good_bins=good_bins,
                                                                    method=method, max_intertad_size=mis,
                                                                    max_tad_size=mts))))
    else:
        first_nonnegative_gamma = np.argmax(lower_check >= 0)
        if first_nonnegative_gamma == 0 and lower_check[first_nonnegative_gamma] < 0 and grid[0] != 0:
            logging.error("WHETHER_TO_EXPAND| Your grid lower bound is probably negative! Please, select non-negative lower bound!")
            return
        elif grid[0] == 0:
            pass
        else:
            for g in lower_check[first_nonnegative_gamma:]:
                len_lower_segments.append(len(list(produce_tads_segmentation(mtx, filters, g, ch, good_bins=good_bins,
                                                                        method=method, max_intertad_size=mis,
                                                                        max_tad_size=mts))))

    if len(set(len_upper_segments)) > 1:
        logging.error("WHETHER_TO_EXPAND| Upper bound could be expanded! Gamma optima would be missed!")
        return
    if len(set(len_lower_segments)) > 1:
        logging.error("WHETHER_TO_EXPAND| Lower bound could be expanded! Gamma optima would be missed!")
        return


def adjust_boundaries(mtx, filters, grid, ch, good_bins, method, mis, mts, start_step, eps=1e-2, type='upper'):
    """
    Function to adjust grid's boundaries.
    :param mtx: input numpy matrix of Hi-C contacts.
    :param filters: regions of Hi-C map that should be ignored (white stripes).
    :param grid: grid of search gamma value.
    :param ch: chromosome name.
    :param good_bins: bool mask of good bins.
    :param method: armatus or modularity to produce segmentation.
    :param mis: maximum intertad size for your method.
    :param mts: maximum TAD size.
    :param start_step: start step to search optimal gamma value. It is equal to step in grid param.
    :param eps: delta for mean tad size during gamma search. Normally equal to 1e-2.
    Lower values gives you more accurate optimal gamma value in the end.
    :param type: type of boundary to adjust - lower or upper.
    :return: adjusted grid.
    """
    logging.info("ADJUST_BOUNDARIES| Start searching gamma {} bound for chromosome {}...".format(type, ch))
    if start_step != 1:
        grid = np.asarray([round(x, len(str(start_step).split('.')[1])) for x in grid])
    len_segments_prev = [0]
    bound_1 = grid[-1] if type == 'upper' else grid[0]
    bound_1_prev = grid[-1] if type == 'upper' else grid[0]
    bound_2 = grid[0] if type == 'upper' else grid[-1]
    delta = len(grid)

    is_begin = True

    while delta > 1:
        len_segments = len(list(produce_tads_segmentation(mtx, filters, bound_1, ch, good_bins=good_bins,
                                                     method=method, max_intertad_size=mis, max_tad_size=mts)))
        if is_begin:
            len_segments_prev = len_segments
            is_begin = False

        if len_segments != len_segments_prev:
            bound_2 = bound_1
            if start_step != 1:
                bound_1 = round((bound_1 + bound_1_prev) / 2, len(str(start_step).split('.')[1]))
            else:
                bound_1 = round((bound_1 + bound_1_prev) / 2)
        else:
            len_segments_prev = len_segments
            bound_1_prev = bound_1
            if start_step != 1:
                bound_1 = round((bound_1 + bound_2) / 2, len(str(start_step).split('.')[1]))
            else:
                bound_1 = round((bound_1 + bound_2) / 2)
        delta = abs(int(np.argwhere(grid == bound_1)) - int(np.argwhere(grid == bound_2)))

    bound_gamma_fixed = bound_1
    adj_grid = np.arange(grid[0], grid[np.where(grid == bound_gamma_fixed)[0][0]] + start_step, start_step) \
        if type == 'upper' else np.arange(grid[np.where(grid == bound_gamma_fixed)[0][0]], grid[-1] + start_step, start_step)
    if start_step != 1 and type != 'upper':
        adj_grid = np.array([round(x, len(str(start_step).split('.')[1])) for x in adj_grid])
    logging.info("ADJUST_BOUNDARIES| Found gamma {} bound: {}".format(type, bound_gamma_fixed))
    if adj_grid[-1] - adj_grid[0] - start_step <= eps and type != 'upper':
        logging.error("ADJUST_BOUNDARIES| You probably out of gamma region of interest! Please, change the grid!")
        return
    else:
        return adj_grid


def find_global_optima(mtx, filters, adj_grid, ch, good_bins, method, mis, mts, start_step, df, expected, resolution):
    """
    Function to find global gamma optima by the given adjusted (or not) grid.
    :param mtx: input numpy matrix of Hi-C contacts.
    :param filters: regions of Hi-C map that should be ignored (white stripes).
    :param adj_grid: adjusted grid of search gamma value.
    :param ch: chromosome name.
    :param good_bins: bool mask of good bins.
    :param method: armatus or modularity to produce segmentation.
    :param mis: maximum intertad size for your method.
    :param mts: maximum TAD size.
    :param start_step: start step to search optimal gamma value. It is equal to step in grid param.
    :param df: dataframe to fill segmentation for current chromosome.
    :param expected: tad size to be expected. For Drosophila melanogaster it could be 120000, 60000 or 30000 bp.
    :param resolution: Hi-C resolution of your coolfiles.
    :return: renew dataframe with segmentation of current chromosome and optimal gamma for this segmentation.
    """
    logging.info("FIND_GLOBAL_OPTIMA| Running TAD search using new adgusted grid for chromosome {}...".format(ch))

    new_grid = np.arange(adj_grid[0], adj_grid[-1] + start_step, start_step)

    segments_0 = produce_tads_segmentation(mtx, filters, new_grid[0], ch, good_bins=good_bins,
                                      method=method, max_intertad_size=mis, max_tad_size=mts)
    mean_tad_size_prev = np.mean(segments_0[:, 1] - segments_0[:, 0])
    gamma_prev = new_grid[0]
    cov_prev = np.sum(segments_0[:, 1] - segments_0[:, 0])

    df_tmp = pd.DataFrame(columns=['bgn', 'end', 'gamma', 'method'], index=np.arange(len(segments_0)))
    df_tmp.loc[:, ['bgn', 'end']] = segments_0
    df_tmp['gamma'] = new_grid[0]
    df_tmp['method'] = method
    df_tmp['ch'] = ch
    df = pd.concat([df, df_tmp])

    local_optimas = {}
    mean_tad_sizes = []
    covs = []
    mean_tad_sizes.append(mean_tad_size_prev)
    covs.append(cov_prev)

    for gamma in new_grid[1:]:
        segments = produce_tads_segmentation(mtx, filters, gamma, ch, good_bins=good_bins,
                                        method=method, max_intertad_size=mis, max_tad_size=mts)
        mean_tad_size = np.mean(segments[:, 1] - segments[:, 0])
        mean_tad_sizes.append(mean_tad_size)
        cov = np.sum(segments[:, 1] - segments[:, 0])
        covs.append(cov)

        df_tmp = pd.DataFrame(columns=['bgn', 'end', 'gamma', 'method'], index=np.arange(len(segments)))
        df_tmp.loc[:, ['bgn', 'end']] = segments
        df_tmp['gamma'] = gamma
        df_tmp['method'] = method
        df_tmp['ch'] = ch
        df = pd.concat([df, df_tmp])

        if (mean_tad_size - expected / resolution) * (mean_tad_size_prev - expected / resolution) <= 0:
            if abs(mean_tad_size - expected / resolution) <= abs(mean_tad_size_prev - expected / resolution):
                local_optimas[gamma] = cov
            else:
                local_optimas[gamma_prev] = cov_prev

        gamma_prev = gamma
        cov_prev = cov
        mean_tad_size_prev = mean_tad_size

    local_optimas[new_grid[np.argmin([abs(x - expected / resolution) for x in mean_tad_sizes])]] = covs[
        np.argmin([abs(x - expected / resolution) for x in mean_tad_sizes])]
    opt_gamma = max(local_optimas.items(), key=operator.itemgetter(1))[0]

    logging.info("FIND_GLOBAL_OPTIMA| Found optimal gamma for chromosome {}: {}".format(ch, opt_gamma))

    return df, opt_gamma


def adjust_global_optima(mtx, filters, opt_gamma, opt_gammas, ch, good_bins, method, mis, mts, start_step, df_concretized, expected, resolution, eps=1e-2):
    """
    Function to adjust global optima gamma value to achieve more accurate segmentation.
    :param mtx: input numpy matrix of Hi-C contacts.
    :param filters: regions of Hi-C map that should be ignored (white stripes).
    :param opt_gamma: optimal gamma value that we want to adjust.
    :param opt_gammas: python dictionary to store adjusted optimal gamma values for each chromosome.
    :param ch: chromosome name.
    :param good_bins: bool mask of good bins.
    :param method: armatus or modularity to produce segmentation.
    :param mis: maximum intertad size for your method.
    :param mts: maximum TAD size.
    :param start_step: start step to search optimal gamma value. It is equal to step in grid param.
    :param df_concretized: dataframe to fill optimal segmentation for current chromosome (based on adjusted optimal gamma).
    :param expected: tad size to be expected. For Drosophila melanogaster it could be 120000, 60000 or 30000 bp.
    :param resolution: Hi-C resolution of your coolfiles.
    :param eps: delta for mean tad size during gamma search. Normally equal to 1e-2.
    Lower values gives you more accurate optimal gamma value in the end.
    :return: renew dataframe with optimal segmentation of current chromosome and python dictionary with
    optimal gamma for this segmentation.
    """
    logging.info("ADJUST_GLOBAL_OPTIMA| Running TAD search to concretize optimal gamma for chromosome {0} "
                 "reducing the step of search...".format(ch))
    segments = produce_tads_segmentation(mtx, filters, opt_gamma, ch, good_bins=good_bins,
                                    method=method, max_intertad_size=mis, max_tad_size=mts)
    mean_tad_size = np.mean(segments[:, 1] - segments[:, 0])
    mts_prev = abs(expected / resolution - mean_tad_size)

    new_opt_gamma = opt_gamma
    step = start_step
    new_grid = np.arange(new_opt_gamma - step, new_opt_gamma + step, step / 10)
    mean_tad_size = []
    for gamma in new_grid:
        segments = produce_tads_segmentation(mtx, filters, gamma, ch, good_bins=good_bins,
                                        method=method, max_intertad_size=mis, max_tad_size=mts)
        mean_tad_size.append(np.mean(segments[:, 1] - segments[:, 0]))

    new_opt_gamma = new_grid[np.argmin([abs(x - expected / resolution) for x in mean_tad_size])]
    mts_cur = np.min([abs(x - expected / resolution) for x in mean_tad_size])
    step /= 10

    while abs(mts_cur - mts_prev) > eps:
        mts_prev = mts_cur
        new_grid = np.arange(new_opt_gamma - step, new_opt_gamma + step, step / 10)
        mean_tad_size = []
        for gamma in new_grid:
            segments = produce_tads_segmentation(mtx, filters, gamma, ch, good_bins=good_bins,
                                            method=method, max_intertad_size=mis, max_tad_size=mts)
            mean_tad_size.append(np.mean(segments[:, 1] - segments[:, 0]))

        new_opt_gamma = new_grid[np.argmin([abs(x - expected / resolution) for x in mean_tad_size])]
        mts_cur = np.min([abs(x - expected / resolution) for x in mean_tad_size])
        step /= 10

    segments = produce_tads_segmentation(mtx, filters, new_opt_gamma, ch, good_bins=good_bins,
                                    method=method, max_intertad_size=mis, max_tad_size=mts, final=True)
    df_tmp = pd.DataFrame(columns=['bgn', 'end', 'gamma', 'method'], index=np.arange(len(segments)))
    df_tmp.loc[:, ['bgn', 'end']] = segments
    df_tmp['gamma'] = new_opt_gamma
    df_tmp['method'] = method
    df_tmp['ch'] = ch
    df_concretized = pd.concat([df_concretized, df_tmp])

    opt_gammas[ch] = new_opt_gamma

    logging.info("ADJUST_GLOBAL_OPTIMA| Found adjusted optimal gamma for chromosome {0}: {1}".format(ch, new_opt_gamma))

    return df_concretized, opt_gammas


def get_noisy_stripes(datasets, ch, method, resolution, exp='3-4h', percentile=99.9):
    """
    Function to get noisy regions from Hi-C contact matrix of given stage and chromosome.
    :param datasets: python dictionary with loaded chromosomes and stages.
    :param ch: chromosome name.
    :param method: segmentation method (only armatus, modularity and insulation available).
    :param resolution: Hi-C resolution of your coolfiles.
    :param exp: stage of development name.
    :param percentile: percentile for cooler preparations and Hi-C vizualization.
    :return: Hi-C noisy stripes (bgn, end) which width is great or equal to w param value
    """
    mtx = datasets[exp][ch].copy()
    mtx[np.isnan(mtx)] = 0
    np.fill_diagonal(mtx, 0)
    mn = np.percentile(mtx[mtx > 0], 100 - percentile)
    mx = np.percentile(mtx[mtx > 0], percentile)
    mtx[mtx <= mn] = mn
    mtx[mtx >= mx] = mx
    mtx = np.log(mtx)
    mtx = mtx - np.min(mtx)

    filters = {}
    v = np.where(np.sum(mtx, axis=1) == 0)[0]
    v_prev = v[0]
    v_tmp = [[v[0]]]
    for i in range(1, len(v) - 1):
        if v[i] - v_prev == 1:
            v_prev = v[i]
        else:
            v_tmp[-1].append(v_prev)
            v_tmp.append([])
            v_tmp[-1].append(v[i])
            v_prev = v[i]
    v_tmp[-1].append(v_prev)
    v_tmp = np.array(v_tmp)

    filt = v_tmp[v_tmp[:, 1] - v_tmp[:, 0] >= 0]

    if method == 'insulation':
        filt_new = []
        for elem in filt:
            filt_new.append([elem[0] * resolution, elem[1] * resolution + resolution])
        filt_new = np.asarray(filt_new)
        filters[ch] = filt_new.copy()
    else:
        filters[ch] = filt.copy()

    good_bins = np.ones(mtx.shape[0], dtype=bool)
    for stripe in filters[ch]:
        if method == 'insulation':
            good_bins[int(stripe[0] / resolution): int(stripe[1] / resolution)] = False
        else:
            good_bins[stripe[0]: stripe[1] + 1] = False

    return filters, mtx, good_bins


def whether_tad_noisy(x, filters, ch, method, resolution=5000, k=3):
    """
    Function determines whether TAD is noisy.
    :param x: TAD (tuple or list of two values - begin and end).
    :param filters: dictionary with noisy regions.
    :param ch: chromosome name.
    :return: True if TAD is 100% noisy (lies in noisy stripe fully or partially), and False otherwise
    """
    for bgn_f, end_f in filters[ch]:
        if method == 'insulation':
            bgn_f_new = bgn_f - resolution * k
            end_f_new = end_f + resolution * k
        else:
            bgn_f_new = bgn_f
            end_f_new = end_f
        if x[0] <= end_f_new and x[0] >= bgn_f_new:
            return True
        if x[1] <= end_f_new and x[1] >= bgn_f_new:
            return True
        if x[1] <= end_f_new and x[0] >= bgn_f_new:
            return True
        if x[0] <= bgn_f_new and x[1] >= end_f_new and end_f_new - bgn_f_new != 0:
            return True
    return False


def calc_noisy_metric(x, filters, ch, method, resolution=5000, k=3):
    """
    Function to calculate noisy metric (characteristic) for each TAD.
    :param x: TAD
    :param filters: dictionary with noisy regions
    :param ch: chromosome name
    :param method: segmentation method (only armatus, modularity and insulation available).
    :return: heuristic metric value for noisy level determination of TAD.
    First we check whether tad "100% noisy" with whether_tad_noisy function.
    If its function returns False for current TAD, then we calculate our metric.
    If True -- we return -1 value of metric.
    """
    if whether_tad_noisy(x, filters, ch, method, resolution, k):
        return -1
    elif method != 'insulation':
        try:
            left_stripe = filters[ch][np.where(filters[ch][:, 1] == filters[ch][:, 1][
                np.argmin(x[0] - filters[ch][:, 1][(x[0] - filters[ch][:, 1]) >= 0])])[0][0]]
        except Exception as e:
            left_stripe = np.array([])
        try:
            right_stripe = \
                filters[ch][np.where(filters[ch][:, 0] == filters[ch][:, 0][(filters[ch][:, 0] - x[1]) >= 0][0])][0]
        except Exception as e:
            right_stripe = np.array([])
        if len(left_stripe) != 0:
            if method == 'insulation':
                left_side_metric = (np.log(x[0] - left_stripe[1]) ** 2)
            else:
                left_side_metric = (np.log(x[0] - left_stripe[1]) ** 2) * np.log(x[1] - x[0])
        else:
            left_side_metric = 1e10
        if len(right_stripe) != 0:
            if method == 'insulation':
                right_side_metric = (np.log(right_stripe[0] - x[1]) ** 2)
            else:
                right_side_metric = (np.log(right_stripe[0] - x[1]) ** 2) * np.log(x[1] - x[0])
        else:
            right_side_metric = 1e10
        return min(left_side_metric, right_side_metric)
    else:
        return 1


def get_d_score(mtx, segmentation):
    """
    Function to calculate D-scores for TADs.
    :param mtx: input numpy matrix of Hi-C contacts.
    :param segmentation: optimal segmentation that we want to map on mtx and then calculate D-scores.
    :return: D-scores for each TAD.
    """
    l = len(mtx)
    segments = np.concatenate([np.array([[0, 0]]), segmentation, np.array([[l, l]])])

    Ds = []
    for i in range(1, len(segments) - 1):
        _, _, p3, p4, _, _ = *segments[i - 1, :], *segments[i, :], *segments[i + 1, :]
        intra = np.nansum(mtx[:p3, p3:p4]) + np.nansum(mtx[p4:, p3:p4])
        inter = (np.nansum(mtx[p3:p4, p3:p4]) - np.trace(mtx[p3:p4, p3:p4])) / 2
        D = inter / intra
        Ds.append(D)

    return Ds
