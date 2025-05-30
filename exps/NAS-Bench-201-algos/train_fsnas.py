##################################################
# Copyright (c) Xuanyi Dong [GitHub D-X-Y], 2020 #
##############################################################################
# Random Search and Reproducibility for Neural Architecture Search, UAI 2019 #
##############################################################################
import os, sys, time, glob, random, argparse
import numpy as np
from copy import deepcopy
import torch
import torch.nn as nn
from torch.utils.tensorboard import SummaryWriter
import torch.backends.cudnn as cudnn

from utils.LR_scheduler import *
from utils.get_strucs import get_struc
from utils.get_num_params import get_num_params

sys.path.insert(0, '../../')

from xautodl.config_utils import load_config, dict2config, configure2str
from xautodl.datasets import get_datasets, get_nas_search_loaders
from xautodl.procedures import (
    prepare_seed,
    prepare_logger,
    save_checkpoint,
    copy_checkpoint,
    get_optim_scheduler,
)
from xautodl.utils import get_model_infos, obtain_accuracy
from xautodl.log_utils import AverageMeter, time_string, convert_secs2time
from xautodl.models import get_cell_based_tiny_net, get_search_spaces
# from nas_201_api import NASBench201API as API
import scipy.stats as stats
import logging
import datetime

import pickle

with open("benchmark_data/cifar10_accs.pkl","rb") as f:
    cifar10_accs = pickle.load(f)    

with open("benchmark_data/cifar100_accs.pkl","rb") as f:
    cifar100_accs = pickle.load(f)    

with open("benchmark_data/imagenet_accs.pkl","rb") as f:
    imagenet_accs = pickle.load(f)  
    
with open("benchmark_data/num_params.pkl","rb") as f:
    num_params = pickle.load(f)    
    
with open("benchmark_data/kendal_320_idx.pkl","rb") as f:
    eval_arch_list = pickle.load(f)   


def str2bool(v):
    if isinstance(v, bool):
       return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

parser = argparse.ArgumentParser(description="NB201_spos")
parser.add_argument('--log_dir', type=str, default='logs/tmp')
parser.add_argument('--file_name', type=str, default='tmp')
parser.add_argument('--seed', type=int, default=0)

parser.add_argument('--epochs', type=int, default=300)
parser.add_argument('--lr', type=float, default= 0.025)
parser.add_argument('--momentum', type=float, default=0.9)
parser.add_argument('--wd', type=float, default=0.0005)
parser.add_argument('--nesterov', default=True, type = str2bool)

parser.add_argument('--train_batch_size', type=int, default=64)
parser.add_argument('--val_batch_size', type=int, default=256)

parser.add_argument('--method', type=str, choices=['baseline', 'dynas'])
parser.add_argument('--max_coeff', type=float, default=4.0, help='gamma_max')
args = parser.parse_args()


os.chdir('../../')

if args.seed is not None:
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    os.environ["PYTHONHASHSEED"] = str(args.seed)
    cudnn.deterministic = True
    cudnn.benchmark = False 


print('=*' * 20)
print(args.file_name)
print('=*' * 20)

epochs = args.epochs
writer = SummaryWriter(args.log_dir)

search_space = get_search_spaces("cell", 'nas-bench-201')
model_config = dict2config(
    {
        "name": "RANDOM",
        "C": 16,
        "N": 5,
        "max_nodes": 4,
        "num_classes": 10,
        "space": search_space,
        "affine": False,
        "track_running_stats": bool(0),
    },
    None,
)


criterion = torch.nn.CrossEntropyLoss()

criterion = criterion.cuda()

train_data, valid_data, _, _ = get_datasets( # train_data: trainset, valid_data: testset
        'cifar10', './dataset', -1
    )

search_loader, _, valid_loader = get_nas_search_loaders( 
        train_data,                                      
        valid_data,                                      
        'cifar10',
        "configs/nas-benchmark/",
        (64, 256), 
        4,
    )

# logger.log(f'search_loader_num: {len(search_loader)}, valid_loader_num: {len(valid_loader)}')

if args.method == 'baseline':
    def get_new_model_optimizer_scheduler():
        network = get_cell_based_tiny_net(model_config)
        optimizer = torch.optim.SGD(
            params = network.parameters(),
            lr = 0.025,
            momentum = args.momentum,
            weight_decay = args.wd,
            nesterov = args.nesterov 
        #     nesterov = False
        )
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer,
            T_max = args.epochs * len(search_loader),
            eta_min = 0
        )

        return network.cuda(), optimizer, scheduler

elif args.method == 'dynas':
    def get_new_model():
        network = get_cell_based_tiny_net(model_config)
        
        return network.cuda()

    C_min = get_num_params(get_struc()[0])
    C_max = get_num_params(get_struc()[11718])

    r_max = args.max_coeff
    r_min = 1/r_max

    w = -(r_max-r_min)/(np.log(C_max)-np.log(C_min))
    tau = r_min - w*np.log(C_max)

    def get_LR_exp_coeff(num_param):
        return w * np.log(num_param) + tau

    def param_adaptive_LR(exp_coeff, cur_ep, total_ep = args.epochs * len(search_loader), eta_min = 0):
        y = ((-cur_ep+total_ep)) ** exp_coeff / (total_ep ** exp_coeff/ (1 - eta_min)) + eta_min
        return float(y)

nr_layer = 6
nr_state = 5

if args.method == 'baseline':
    supernets = []
    for i in range(nr_state):
        supernets.append(get_new_model_optimizer_scheduler())

elif args.method == 'dynas':
    supernets = []
    for i in range(nr_state):
        supernets.append(get_new_model())

from xautodl.models.cell_searchs.genotypes import Structure

genotypes = []
op_names = deepcopy(search_space)
for i in range(1, 4):
    xlist = []
    for j in range(i):
        op_name = random.choice(op_names)
        xlist.append((op_name, j))
    genotypes.append(tuple(xlist))
arch = Structure(genotypes)

if args.method == 'baseline':
    edge2index = supernets[0][0].edge2index

elif args.method == 'dynas':
    edge2index = supernets[0].edge2index
    
max_nodes = 4
def genotype(enc): # upon calling, the caller should pass the "theta" into this object as "alpha" first
#     theta = torch.softmax(_arch_parameters, dim=-1) * enc
    theta = enc
    genotypes = []
    for i in range(1, max_nodes):
      xlist = []
      for j in range(i):
        node_str = '{:}<-{:}'.format(i, j)
        with torch.no_grad():
          weights = theta[ edge2index[node_str] ]
          op_name = op_names[ weights.argmax().item() ]
        xlist.append((op_name, j))
      genotypes.append( tuple(xlist) )
    return Structure( genotypes )

struc = get_struc()


def get_rand_arch(weight_split_edge, op_num):
    rand_arch = list(np.random.randint(nr_state) for i in range(nr_layer))
    rand_arch[weight_split_edge] = op_num
    
    return rand_arch

def to_struc(tup):
    tensor = torch.zeros(nr_layer, nr_state)
    for i, val in enumerate(tup):
        tensor[i, val] = 1

    return tensor

# weight_split_edge = random.randint(0, nr_layer-1)
weight_split_edge = 0 # This is how official code of FSNAS is implemented.

logging.info(f'weight_split_{weight_split_edge}')
print(f'weight_split_{weight_split_edge}') 

if args.method == 'dynas':
    while True:
        MS_split_edge = random.randrange(6)
        if MS_split_edge != weight_split_edge:
            break

    logging.info(f'MS_split_{MS_split_edge}')
    print(f'MS_split_{MS_split_edge}')

if args.method == 'baseline':
    for op_num, (network, optimizer, scheduler) in enumerate(supernets):
        total_iter = 0
        for ep in range(epochs):
            network.train()
            for i, (input, label, _, _) in enumerate(search_loader):
                input = input.cuda()
                label = label.cuda()

                rand_arch = get_rand_arch(weight_split_edge, op_num)

                network.arch_cache = genotype(to_struc(rand_arch))

                optimizer.zero_grad()

                _, pred = network(input)
                loss = criterion(pred, label)
                loss.backward()
                nn.utils.clip_grad_norm_(network.parameters(), 5)
                optimizer.step()

                scheduler.step()           

                writer.add_scalar('train/subnet_loss', loss.item(), total_iter)

                base_prec1, base_prec5 = obtain_accuracy(
                    pred.data, label.data, topk=(1, 5)
                )

                writer.add_scalar('train/subnet_top1', base_prec1, total_iter)
                writer.add_scalar('train/subnet_top5', base_prec5, total_iter)
                total_iter += 1        

            print(f'ep: {ep}, top1: {base_prec1.item()}')

elif args.method == 'dynas':
    for op_num, network in enumerate(supernets):
        total_iter = 0
        
        optimizers = []

        for i in range(5):
            optimizers.append(torch.optim.SGD(
            params = network.parameters(),
            lr = args.lr,
            momentum = args.momentum,
            weight_decay = args.wd,
            nesterov = args.nesterov 
        ))


        schedulers = [AdaptiveParamSchedule(
            optimizer = optimizer,
            epochs = args.epochs * len(search_loader),
            eta_min = 0
        ) for optimizer in optimizers
                    ] 
         
        for ep in range(epochs):
            network.train()
            for i, (input, label, _, _) in enumerate(search_loader):
                input = input.cuda()
                label = label.cuda()
                
                rand_arch = get_rand_arch(weight_split_edge, op_num)

                network.arch_cache = genotype(to_struc(rand_arch))

                for j in range(5):
                    if to_struc(rand_arch)[MS_split_edge,j] == 1:
                        num_param = get_num_params(to_struc(rand_arch))

                        schedulers[j].exp_coeff = get_LR_exp_coeff(num_param)
                        schedulers[j].cur_ep = total_iter
                        schedulers[j].step()

                        optimizers[j].zero_grad()

                        _, pred = network(input)
                        loss = criterion(pred, label)
                        loss.backward()
                        nn.utils.clip_grad_norm_(network.parameters(), 5)
                        optimizers[j].step()

                writer.add_scalar('train/subnet_loss', loss.item(), total_iter)

                base_prec1, base_prec5 = obtain_accuracy(
                    pred.data, label.data, topk=(1, 5)
                )

                writer.add_scalar('train/subnet_top1', base_prec1, total_iter)
                writer.add_scalar('train/subnet_top5', base_prec5, total_iter)
                total_iter += 1

            print(f'OP: {op_num}, ep: {ep}, top1: {base_prec1.item()}')

        

print('================Evaluation start================')
loader_iter = iter(valid_loader)
valid_accs = []

for i in range(len(struc)):        
    sub_supernet_num = int(struc[i][weight_split_edge].nonzero(as_tuple=False))

    if args.method == 'baseline':
        network, _, _ = supernets[sub_supernet_num]

    elif args.method == 'dynas':
        network = supernets[sub_supernet_num]

    network.arch_cache = genotype(struc[i])
        
    with torch.no_grad():
        network.eval()
        correct_classified = 0
        total = 0
        for j, (input, label) in enumerate(valid_loader):
            input = input.cuda()
            label = label.cuda()

            _, pred = network(input)
            _, predicted = torch.max(pred.data,1)

            total += pred.size(0)
            correct_classified += (predicted == label).sum().item()      

        valid_acc = correct_classified/total

        valid_accs.append(valid_acc)

#     print(f'=============={i}==============')
    print(f'struc_num: {i}, valid_acc: {valid_acc * 100}%, real_acc: {cifar10_accs[i]}%, num_params: {num_params[i]}M')
    logging.info(f'struc_num: {i}, valid_acc: {valid_acc * 100}%, real_acc: {cifar10_accs[i]}%, num_params: {num_params[i]}M')

import pickle

# For reporting 
with open(f"./exps/NAS-Bench-201-algos/valid_accs/{args.file_name}.pkl","wb") as f:
    pickle.dump(valid_accs, f)        

print(f'############# Kendall #############') 

cifar10_valid_true_tau_320, _ = stats.kendalltau(np.array(valid_accs)[eval_arch_list], np.array(cifar10_accs)[eval_arch_list])     
cifar100_valid_true_tau_320, _ = stats.kendalltau(np.array(valid_accs)[eval_arch_list], np.array(cifar100_accs)[eval_arch_list])   
imagenet_valid_true_tau_320, _ = stats.kendalltau(np.array(valid_accs)[eval_arch_list], np.array(imagenet_accs)[eval_arch_list])

print(f'cifar10_kendall: {cifar10_valid_true_tau_320}')
print(f'cifar100_kendall: {cifar100_valid_true_tau_320}')
print(f'imagenet_kendall: {imagenet_valid_true_tau_320}')

writer.add_scalar('Kendall_320/cifar10', cifar10_valid_true_tau_320, total_iter)
writer.add_scalar('Kendall_320/cifar100', cifar100_valid_true_tau_320, total_iter)
writer.add_scalar('Kendall_320/imagenet', imagenet_valid_true_tau_320, total_iter)

logging.info(f'=============={args.file_name}==============')

logging.info(f'############# Kendall 320 #############') 
logging.info(f'cifar10_kendall: {cifar10_valid_true_tau_320}')
logging.info(f'cifar100_kendall: {cifar100_valid_true_tau_320}')
logging.info(f'imagenet_kendall: {imagenet_valid_true_tau_320}')
