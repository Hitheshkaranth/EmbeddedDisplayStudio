// faces/nativefaces.h -- registration of the QML module Shadcn.Native.
//
// The module is compiled into the hmi-gui binary (no plugin, no qmldir):
// registerNativeFaces() registers every face type plus NativeProbe, the
// empty type Theme.nativeFaces instantiates to detect the module. main.cpp
// calls it unless HMI_NATIVE_FACES=0, which keeps the Canvas painters in
// use for A/B comparison on the panel.
#pragma once

#include <QObject>
#include <QStringList>

namespace hmi {

// Instantiated by Theme.qml's probe; carries nothing.
class NativeProbe : public QObject
{
    Q_OBJECT
public:
    using QObject::QObject;
};

// Registers Shadcn.Native 1.0. Safe to call more than once.
void registerNativeFaces();

// The face names, in registration order: "ClusterGauge", ... Each has a
// <Name>Face type here and a faces/{canvas,native}/<Name>Face.qml in the kit.
QStringList nativeFaceNames();

} // namespace hmi
