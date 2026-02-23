import 'package:flutter/material.dart';
import 'report_screen.dart';
import 'my_reports_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _currentIndex = 0;

  static const List<Widget> _screens = [
    ReportScreen(),
    MyReportsScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('TrustBond'),
      ),
      body: IndexedStack(
        index: _currentIndex,
        children: _screens,
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (int index) {
          setState(() {
            _currentIndex = index;
          });
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.edit_note),
            label: 'Report',
          ),
          NavigationDestination(
            icon: Icon(Icons.assignment),
            label: 'My Reports',
          ),
        ],
      ),
    );
  }
}
