# codemao-work-export

编程猫作品源码反编译工具
输入作品 ID，导出 `.bcm4` / `.bcm` / `.json` 源码文件
基于 [S-LIGHTNING](https://github.com/S-LIGHTNING) 的 [源码反编译器4](https://github.com/S-LIGHTNING/Kitten-4-Decompiler)

**单文件，更方便**

## 用法

```
python Main.py
```
## 支持类型

| 类型 | 扩展名 |
|------|------|
| KITTEN4 | .bcm4 |
| KITTEN3 | .bcm |
| COCO | .json |

## 已知问题
1.积木全部都会在 **0x 0y** 重叠

2.生成出的作品，有可能无法运行或错误
