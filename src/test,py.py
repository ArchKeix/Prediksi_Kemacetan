import torch

print("Nama GPU:", torch.cuda.get_device_name(0))
print("CUDA version:", torch.version.cuda)

x = torch.randn(1000, 1000, device="cuda:0")
y = x @ x

print("Device tensor:", y.device)
print("Tes GPU berhasil!")