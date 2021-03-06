# -*- coding: utf-8 -*-
"""
Created on Tue Feb 22 09:55:41 2022

@author: Max
"""

import numpy as np
import time
from numba import cuda
import warnings
import numba

line_lenght_min = 46
line_lenght_max = 96
best = 15

start_time = time.time()
    
@cuda.jit('void(int8[:], uint64[:], int8[:,:], int8[:], int32[:], uint64[:])')
def ak_func_demo(d_k, d_j, d_max_line, d_best, d_min, d_index_min):
    
    row = cuda.blockIdx.x * cuda.blockDim.x + cuda.threadIdx.x
    
    m = row + d_j[0] * 2**31 # поправка на батчер (batch = max(0, k - 33)) по формуле d_j[0] * 2 ** [k старта батчера - 2]
    
    d_max_line[row][0] = 0
    d_max_line[row][1] = d_k[0]
    line_max = max(3, d_k[0] // d_best[0] + 1)
    
    flag = 0
    
    for d in range(1, d_k[0]):
        
        akf = 0
        g = 0
        
        while d+g < d_k[0] :
            
            m_div_pow_2_g = m // pow(2, g)
            akf += ((m_div_pow_2_g // pow(2, d) % 2)*2 - 1) * ((m_div_pow_2_g % 2)*2 - 1)
            g += 1
            
        akf = abs(akf)
          
        if (akf > line_max) or (flag == 0 and d > 5):
            d_max_line[row] = d_k[0]
            break
        else:
            d_max_line[row][0] = max(akf, d_max_line[row][0])
            if akf == 0:
                d_max_line[row][1] = min(d, d_max_line[row][1])
                flag = 1

    # Поиск оптимального сигнала и его индекса
    
    cuda.atomic.min(d_min, 0, d_max_line[row][0])
    if d_max_line[row][0] == d_min[0]:
        if d_max_line[row][1] <= d_max_line[d_index_min[0]][1]:
            d_index_min[0] = row

@numba.jit(nopython = True) 
def get_bin(count, k):
    line = np.zeros(k, dtype=np.int8)
    
    for i in range(len(line)):
        line[i] = count % 2 * 2 - 1
        count //= 2

    akf = np.zeros_like(line)

    for d in range(k):
        for g in range(k):
            if d+g < k :
                akf[d] += line[d+g] * line[g]
    return line, akf

batch = 0
tpb = cuda.get_current_device().WARP_SIZE

d_best = cuda.to_device(np.array([best], dtype=np.int8))

for k in range(line_lenght_min, line_lenght_max + 1): 

    batch = max(0, k - 32)
    
    batch_pow = pow(2, batch)
    
    power = k - 1 - batch
        
    k_pow = pow(2, power)
    
    bpg = int(np.ceil(k_pow / tpb))
    
    d_k = cuda.to_device(np.array([k],  dtype=np.int8))
    d_max_line = cuda.device_array((k_pow, 2), dtype=np.int8)
    d_index_min = cuda.to_device(np.array([0], dtype=np.uint64))
    
    best_on_line = 0

    for j in range(batch_pow):
        
        d_min = cuda.to_device(np.array([100], dtype=np.int32))
                           
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ak_func_demo[bpg, tpb](
                                   d_k,
                                   cuda.to_device(np.array([j], dtype=np.uint64)), # d_j
                                   d_max_line,
                                   d_best,
                                   d_min,
                                   d_index_min
                                   )
            
            #s = d_max_line.copy_to_host()                   
            #print(s)

        optimal_amp = d_min.copy_to_host()[0]
        
        if k/optimal_amp >= best :
            best = k//optimal_amp
            d_best = cuda.to_device(np.array([best], dtype=np.int8))
        
        best_on_line = k/optimal_amp
        index_min = int(d_index_min.copy_to_host()[0])
        optimal_line, optimal_akf = get_bin(index_min + j * 2**31, k)
        
        text_message = f'\n{ optimal_line } \
                        \n{ optimal_akf } \
                        \n{ k } / { optimal_amp } = { best_on_line } - Batch: { j+1 }/{ batch_pow }, { np.round((time.time() - start_time), 2) } sec\n'

        print (text_message)
        f = open('akf_bin.txt', 'a')
        f.write(text_message)
        f.close()
            
    d_max_line = cuda.device_array(1, dtype=np.int8)
                
    print("")
