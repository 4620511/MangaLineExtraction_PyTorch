import torch.nn as nn


class _BnReluConv(nn.Module):
    def __init__(self, in_filters, nb_filters, fw, fh, subsample=1):
        super(_BnReluConv, self).__init__()
        self.model = nn.Sequential(
            nn.BatchNorm2d(in_filters, eps=1e-3),
            nn.LeakyReLU(0.2),
            nn.Conv2d(
                in_filters, nb_filters, (fw, fh), stride=subsample, padding=(fw // 2, fh // 2), padding_mode="zeros"
            ),
        )

    def forward(self, x):
        return self.model(x)


class _UBnReluConv(nn.Module):
    def __init__(self, in_filters, nb_filters, fw, fh, subsample=1):
        super(_UBnReluConv, self).__init__()
        self.model = nn.Sequential(
            nn.BatchNorm2d(in_filters, eps=1e-3),
            nn.LeakyReLU(0.2),
            nn.Conv2d(in_filters, nb_filters, (fw, fh), stride=subsample, padding=(fw // 2, fh // 2)),
            nn.Upsample(scale_factor=2, mode="nearest"),
        )

    def forward(self, x):
        return self.model(x)


class _Shortcut(nn.Module):
    def __init__(self, in_filters, nb_filters, subsample=1):
        super(_Shortcut, self).__init__()
        self.process = False
        self.model = None
        if in_filters != nb_filters or subsample != 1:
            self.process = True
            self.model = nn.Sequential(nn.Conv2d(in_filters, nb_filters, (1, 1), stride=subsample))

    def forward(self, x, y):
        if self.process:
            y0 = self.model(x)
            return y0 + y
        else:
            return x + y


class _UShortcut(nn.Module):
    def __init__(self, in_filters, nb_filters, subsample):
        super(_UShortcut, self).__init__()
        self.process = False
        self.model = None
        if in_filters != nb_filters:
            self.process = True
            self.model = nn.Sequential(
                nn.Conv2d(in_filters, nb_filters, (1, 1), stride=subsample, padding_mode="zeros"),
                nn.Upsample(scale_factor=2, mode="nearest"),
            )

    def forward(self, x, y):
        if self.process:
            return self.model(x) + y
        else:
            return x + y


class BasicBlock(nn.Module):
    def __init__(self, in_filters, nb_filters, init_subsample=1):
        super(BasicBlock, self).__init__()
        self.conv1 = _BnReluConv(in_filters, nb_filters, 3, 3, subsample=init_subsample)
        self.residual = _BnReluConv(nb_filters, nb_filters, 3, 3)
        self.shortcut = _Shortcut(in_filters, nb_filters, subsample=init_subsample)

    def forward(self, x):
        x1 = self.conv1(x)
        x2 = self.residual(x1)
        return self.shortcut(x, x2)


class _UBasicBlock(nn.Module):
    def __init__(self, in_filters, nb_filters, init_subsample=1):
        super(_UBasicBlock, self).__init__()
        self.conv1 = _UBnReluConv(in_filters, nb_filters, 3, 3, subsample=init_subsample)
        self.residual = _BnReluConv(nb_filters, nb_filters, 3, 3)
        self.shortcut = _UShortcut(in_filters, nb_filters, subsample=init_subsample)

    def forward(self, x):
        y = self.residual(self.conv1(x))
        return self.shortcut(x, y)


class _ResidualBlock(nn.Module):
    def __init__(self, in_filters, nb_filters, repetitions, is_first_layer=False):
        super(_ResidualBlock, self).__init__()
        layers = []
        for i in range(repetitions):
            init_subsample = 1
            if i == repetitions - 1 and not is_first_layer:
                init_subsample = 2
            if i == 0:
                l = BasicBlock(in_filters=in_filters, nb_filters=nb_filters, init_subsample=init_subsample)
            else:
                l = BasicBlock(in_filters=nb_filters, nb_filters=nb_filters, init_subsample=init_subsample)
            layers.append(l)

        self.model = nn.Sequential(*layers)

    def forward(self, x):
        return self.model(x)


class _UpsamplingResidualBlock(nn.Module):
    def __init__(self, in_filters, nb_filters, repetitions):
        super(_UpsamplingResidualBlock, self).__init__()
        layers = []
        for i in range(repetitions):
            l = None
            if i == 0:
                l = _UBasicBlock(in_filters=in_filters, nb_filters=nb_filters)  # (input)
            else:
                l = BasicBlock(in_filters=nb_filters, nb_filters=nb_filters)  # (input)
            layers.append(l)

        self.model = nn.Sequential(*layers)

    def forward(self, x):
        return self.model(x)


class MangaLineExtractor(nn.Module):
    def __init__(self):
        super(MangaLineExtractor, self).__init__()
        self.block0 = _ResidualBlock(in_filters=1, nb_filters=24, repetitions=2, is_first_layer=True)  # (input)
        self.block1 = _ResidualBlock(in_filters=24, nb_filters=48, repetitions=3)  # (block0)
        self.block2 = _ResidualBlock(in_filters=48, nb_filters=96, repetitions=5)  # (block1)
        self.block3 = _ResidualBlock(in_filters=96, nb_filters=192, repetitions=7)  # (block2)
        self.block4 = _ResidualBlock(in_filters=192, nb_filters=384, repetitions=12)  # (block3)

        self.block5 = _UpsamplingResidualBlock(in_filters=384, nb_filters=192, repetitions=7)  # (block4)
        self.res1 = _Shortcut(in_filters=192, nb_filters=192)  # (block3, block5, subsample=(1,1))

        self.block6 = _UpsamplingResidualBlock(in_filters=192, nb_filters=96, repetitions=5)  # (res1)
        self.res2 = _Shortcut(in_filters=96, nb_filters=96)  # (block2, block6, subsample=(1,1))

        self.block7 = _UpsamplingResidualBlock(in_filters=96, nb_filters=48, repetitions=3)  # (res2)
        self.res3 = _Shortcut(in_filters=48, nb_filters=48)  # (block1, block7, subsample=(1,1))

        self.block8 = _UpsamplingResidualBlock(in_filters=48, nb_filters=24, repetitions=2)  # (res3)
        self.res4 = _Shortcut(in_filters=24, nb_filters=24)  # (block0,block8, subsample=(1,1))

        self.block9 = _ResidualBlock(in_filters=24, nb_filters=16, repetitions=2, is_first_layer=True)  # (res4)
        self.conv15 = _BnReluConv(in_filters=16, nb_filters=1, fh=1, fw=1, subsample=1)  # (block7)

    def forward(self, x):
        x0 = self.block0(x)
        x1 = self.block1(x0)
        x2 = self.block2(x1)
        x3 = self.block3(x2)
        x4 = self.block4(x3)

        x5 = self.block5(x4)
        res1 = self.res1(x3, x5)

        x6 = self.block6(res1)
        res2 = self.res2(x2, x6)

        x7 = self.block7(res2)
        res3 = self.res3(x1, x7)

        x8 = self.block8(res3)
        res4 = self.res4(x0, x8)

        x9 = self.block9(res4)
        y = self.conv15(x9)

        return y
