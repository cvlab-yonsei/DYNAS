# Pytorch implementation of DYNAS
This is the implementation of the paper "Subnet-Aware Dynamic Supernet Training for Neural Architecture Search".

For detailed information, please checkout the project site [[website](https://cvlab.yonsei.ac.kr/projects/DYNAS/)] or the paper [[arXiv](https://arxiv.org/abs/2503.10740)].




## Requirements
This repository has been tested with the following libraries:
```bash
python==3.8.8
numpy==1.19.2
torch==1.8.1
```

## Getting started

```bash
cd exps/NAS-Bench-201-algos

# Example code for SPOS
python train_spos.py \
    --log_dir logs/spos_base \
    --file_name spos_base \
    --method baseline


# Example code for SPOS + Ours
python train_spos.py \
    --log_dir logs/spos_dynamic \
    --file_name spos_dynamic \
    --method dynas
```

- The work is conducted using the NAS-Bench-201 dataset.
- You can run for other baselines (FairNAS and FSNAS) in a similar way.
- Our code is mainly built on [AutoDL](https://github.com/D-X-Y/AutoDL-Projects/tree/main).

## Citation

```
@inproceedings{jeon2025subnet,
  title={Subnet-Aware Dynamic Supernet Training for Neural Architecture Search},
  author={Jeon, Jeimin and Oh, Youngmin and Lee, Junghyup and Baek, Donghyeon and Kim, Dohyung and Eom, Chanho and Ham, Bumsub},
  booktitle={Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition},
  year={2025}
}
```




