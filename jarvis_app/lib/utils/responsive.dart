import 'package:flutter/material.dart';

enum FormFactor { compact, medium, expanded }

extension Responsive on BuildContext {
  Size get screen => MediaQuery.of(this).size;
  double get shortest => screen.shortestSide;
  double get longest => screen.longestSide;
  EdgeInsets get insets => MediaQuery.of(this).viewPadding;
  bool get isDark => Theme.of(this).brightness == Brightness.dark;
  bool get reducedMotion => MediaQuery.of(this).disableAnimations;

  FormFactor get ff {
    final s = shortest;
    if (s >= 840) return FormFactor.expanded;
    if (s >= 600) return FormFactor.medium;
    return FormFactor.compact;
  }

  double scale(double base, {double min = 0.85, double max = 1.25}) {
    final factor = (shortest / 390).clamp(min, max);
    return base * factor;
  }
}

class Gap {
  static SizedBox v(double h) => SizedBox(height: h);
  static SizedBox h(double w) => SizedBox(width: w);
}

class AdaptiveScaffold extends StatelessWidget {
  final Widget body;
  final Widget? bottomBar;
  final Widget? sideRail;
  final PreferredSizeWidget? appBar;
  final Color? background;
  final bool resizeToAvoidBottomInset;
  const AdaptiveScaffold({
    super.key,
    required this.body,
    this.bottomBar,
    this.sideRail,
    this.appBar,
    this.background,
    this.resizeToAvoidBottomInset = true,
  });

  @override
  Widget build(BuildContext context) {
    final ff = context.ff;
    final useRail = ff != FormFactor.compact && sideRail != null;
    return Scaffold(
      backgroundColor: background ?? Theme.of(context).scaffoldBackgroundColor,
      appBar: appBar,
      resizeToAvoidBottomInset: resizeToAvoidBottomInset,
      bottomNavigationBar: useRail ? null : bottomBar,
      body: SafeArea(
        top: appBar == null,
        bottom: false,
        left: true,
        right: true,
        child: useRail
            ? Row(children: [sideRail!, Expanded(child: body)])
            : body,
      ),
    );
  }
}
