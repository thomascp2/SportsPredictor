
============================================================
  HITS  (n_test=14,764)
  MAE:      0.5542  (naive mean baseline: 0.8113)
  RMSE:     0.7145
  Improvement over baseline: 31.7%

    Line   N_over   Over%     Acc  Note
  ------------------------------------------------
     0.5    8,475   57.4%   72.2%  +14.8% vs naive
     1.5    2,845   19.3%   81.4%  +0.6% vs naive
     2.5      575    3.9%   96.1%  0.0% vs naive

  Feature importances:
    xwoba                     0.535  ################
    xwoba_14d                 0.276  ########
    avg_la                    0.070  ##
    ev_7d                     0.067  ##
    avg_ev                    0.052  #

============================================================
  TOTAL_BASES  (n_test=14,764)
  MAE:      0.9694  (naive mean baseline: 1.1871)
  RMSE:     1.3496
  Improvement over baseline: 18.3%

    Line   N_over   Over%     Acc  Note
  ------------------------------------------------
     1.5    4,771   32.3%   74.0%  +6.4% vs naive
     2.5    2,774   18.8%   84.3%  +3.1% vs naive
     3.5    1,960   13.3%   88.2%  +1.5% vs naive

  Feature importances:
    xwoba                     0.539  ################
    xwoba_14d                 0.274  ########
    ev_7d                     0.078  ##
    avg_ev                    0.059  #
    avg_la                    0.049  #

============================================================
  HOME_RUNS  (n_test=14,764)
  MAE:      0.1487  (naive mean baseline: 0.1143)
  RMSE:     0.2880
  Improvement over baseline: -30.1%

    Line   N_over   Over%     Acc  Note
  ------------------------------------------------
     0.5    1,588   10.8%   90.4%  +1.1% vs naive
     1.5       93    0.6%   99.4%  +0.0% vs naive

  Feature importances:
    xwoba                     0.497  ##############
    xwoba_14d                 0.265  #######
    ev_7d                     0.093  ##
    avg_la                    0.073  ##
    avg_ev                    0.073  ##

============================================================
  STRIKEOUTS  (n_test=1,553)
  MAE:      1.6135  (naive mean baseline: 1.9878)
  RMSE:     2.0327
  Improvement over baseline: 18.8%

    Line   N_over   Over%     Acc  Note
  ------------------------------------------------
     3.5    1,064   68.5%   75.6%  +7.1% vs naive
     4.5      796   51.3%   68.1%  +16.9% vs naive
     5.5      575   37.0%   71.6%  +8.6% vs naive
     6.5      370   23.8%   79.4%  +3.2% vs naive
     7.5      231   14.9%   85.3%  +0.1% vs naive

  Feature importances:
    whiff_rate                0.351  ##########
    xwoba_allowed             0.314  #########
    park_adjusted_xwoba       0.193  #####
    velocity_trend_7d         0.075  ##
    avg_velocity              0.067  #

============================================================
  WALKS  (n_test=1,553)
  MAE:      0.9575  (naive mean baseline: 1.0457)
  RMSE:     1.2000
  Improvement over baseline: 8.4%

    Line   N_over   Over%     Acc  Note
  ------------------------------------------------
     1.5      778   50.1%   61.4%  +11.3% vs naive
     2.5      368   23.7%   76.3%  0.0% vs naive

  Feature importances:
    xwoba_allowed             0.386  ###########
    park_adjusted_xwoba       0.295  ########
    velocity_trend_7d         0.111  ###
    whiff_rate                0.108  ###
    avg_velocity              0.100  ###

============================================================
  OUTS_RECORDED  (n_test=1,553)
  MAE:      2.6098  (naive mean baseline: 2.7733)
  RMSE:     3.3224
  Improvement over baseline: 5.9%

    Line   N_over   Over%     Acc  Note
  ------------------------------------------------
    14.5      967   62.3%   68.4%  +6.1% vs naive
    17.5      453   29.2%   70.4%  -0.5% vs naive

  Feature importances:
    xwoba_allowed             0.380  ###########
    park_adjusted_xwoba       0.266  #######
    whiff_rate                0.132  ###
    velocity_trend_7d         0.122  ###
    avg_velocity              0.100  ###

============================================================