import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { Alert, AlertDescription } from '../ui/alert';
import { 
  MapPin, 
  Clock, 
  Shield, 
  Users, 
  AlertTriangle, 
  CheckCircle,
  XCircle,
  Navigation,
  ExternalLink
} from 'lucide-react';
import { api } from '../../services/api';

const CommanderDashboard = () => {
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('pending_deployment');
  const [error, setError] = useState(null);

  useEffect(() => {
    loadIncidents();
  }, [statusFilter]);

  const loadIncidents = async () => {
    try {
      setLoading(true);
      const response = await api.get(`/deployment-decisions/commander-dashboard`, {
        params: { status_filter: statusFilter }
      });
      setIncidents(response.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load incidents');
    } finally {
      setLoading(false);
    }
  };

  const handleDeploymentDecision = async (reportId, decisionData) => {
    try {
      await api.post('/deployment-decisions/', decisionData);
      loadIncidents(); // Refresh the data
    } catch (err) {
      alert('Failed to create deployment decision: ' + (err.response?.data?.detail || err.message));
    }
  };

  const getPriorityColor = (priority) => {
    switch (priority?.toLowerCase()) {
      case 'urgent': return 'bg-red-500';
      case 'high': return 'bg-orange-500';
      case 'medium': return 'bg-yellow-500';
      case 'low': return 'bg-green-500';
      default: return 'bg-gray-500';
    }
  };

  const getStatusColor = (status) => {
    switch (status?.toLowerCase()) {
      case 'confirmed': return 'bg-green-100 text-green-800';
      case 'rejected': return 'bg-red-100 text-red-800';
      case 'pending': return 'bg-orange-100 text-orange-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'Unknown';
    const date = new Date(dateString);
    return date.toLocaleString();
  };

  const DeploymentDecisionCard = ({ incident }) => {
    const [showDeploymentForm, setShowDeploymentForm] = useState(false);
    const [deploymentData, setDeploymentData] = useState({
      deployment_status: 'deployed',
      assigned_unit: 'general_patrol',
      deployment_priority: 'medium',
      decision_note: '',
      leader_confirmation_weight: 4
    });

    const handleSubmit = (e) => {
      e.preventDefault();
      handleDeploymentDecision(incident.report_id, {
        ...deploymentData,
        report_id: incident.report_id,
        case_id: incident.case_id
      });
      setShowDeploymentForm(false);
    };

    return (
      <Card className="mb-4 border-l-4 border-l-blue-500">
        <CardHeader className="pb-3">
          <div className="flex justify-between items-start">
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-2">
                <Badge className={getPriorityColor(incident.priority)}>
                  {incident.priority?.toUpperCase()}
                </Badge>
                {incident.report_number && (
                  <Badge variant="outline">{incident.report_number}</Badge>
                )}
                <Badge className={getStatusColor(incident.leader_verification_status)}>
                  {incident.leader_verification_status?.toUpperCase()}
                </Badge>
              </div>
              <CardTitle className="text-lg">{incident.incident_type}</CardTitle>
              <div className="flex items-center gap-4 text-sm text-gray-600 mt-1">
                <div className="flex items-center gap-1">
                  <MapPin className="w-4 h-4" />
                  {incident.location_description}
                </div>
                <div className="flex items-center gap-1">
                  <Clock className="w-4 h-4" />
                  {formatDate(incident.submitted_at)}
                </div>
              </div>
            </div>
            {incident.leader_name && (
              <div className="text-right">
                <div className="text-sm font-medium text-gray-900">
                  {incident.leader_name}
                </div>
                <div className="text-xs text-gray-500">
                  {incident.leader_role?.replace('_', ' ')}
                </div>
                <div className="text-xs text-green-600">
                  ✓ Leader Confirmed
                </div>
              </div>
            )}
          </div>
        </CardHeader>

        <CardContent>
          {!incident.deployment_decision ? (
            <div>
              <Alert className="mb-4">
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription>
                  This incident has been confirmed by local leaders and requires your deployment decision.
                </AlertDescription>
              </Alert>

              {!showDeploymentForm ? (
                <div className="flex gap-2">
                  <Button 
                    onClick={() => setShowDeploymentForm(true)}
                    className="bg-blue-600 hover:bg-blue-700"
                  >
                    <Shield className="w-4 h-4 mr-2" />
                    Make Deployment Decision
                  </Button>
                  <Button 
                    variant="outline"
                    onClick={() => window.open(
                      `https://www.google.com/maps?q=${incident.latitude},${incident.longitude}`,
                      '_blank'
                    )}
                  >
                    <Navigation className="w-4 h-4 mr-2" />
                    View Location
                  </Button>
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="space-y-4 border rounded-lg p-4 bg-gray-50">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium mb-1">Deployment Status</label>
                      <select 
                        className="w-full p-2 border rounded"
                        value={deploymentData.deployment_status}
                        onChange={(e) => setDeploymentData({...deploymentData, deployment_status: e.target.value})}
                      >
                        <option value="deployed">Deploy Team</option>
                        <option value="monitoring">Monitor Only</option>
                        <option value="declined">Decline Deployment</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium mb-1">Assigned Unit</label>
                      <select 
                        className="w-full p-2 border rounded"
                        value={deploymentData.assigned_unit}
                        onChange={(e) => setDeploymentData({...deploymentData, assigned_unit: e.target.value})}
                      >
                        <option value="general_patrol">General Patrol</option>
                        <option value="quick_response">Quick Response Team</option>
                        <option value="counter_terror">Counter Terror</option>
                        <option value="fire_rescue">Fire & Rescue</option>
                      </select>
                    </div>
                  </div>
                  
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium mb-1">Priority</label>
                      <select 
                        className="w-full p-2 border rounded"
                        value={deploymentData.deployment_priority}
                        onChange={(e) => setDeploymentData({...deploymentData, deployment_priority: e.target.value})}
                      >
                        <option value="low">Low</option>
                        <option value="medium">Medium</option>
                        <option value="high">High</option>
                        <option value="urgent">Urgent</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium mb-1">Leader Confirmation Weight</label>
                      <select 
                        className="w-full p-2 border rounded"
                        value={deploymentData.leader_confirmation_weight}
                        onChange={(e) => setDeploymentData({...deploymentData, leader_confirmation_weight: parseInt(e.target.value)})}
                      >
                        <option value={1}>Low (1)</option>
                        <option value={2}>Medium-Low (2)</option>
                        <option value={3}>Medium (3)</option>
                        <option value={4}>Medium-High (4)</option>
                        <option value={5}>High (5)</option>
                      </select>
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm font-medium mb-1">Decision Note</label>
                    <textarea 
                      className="w-full p-2 border rounded"
                      rows={3}
                      placeholder="Reason for deployment decision..."
                      value={deploymentData.decision_note}
                      onChange={(e) => setDeploymentData({...deploymentData, decision_note: e.target.value})}
                    />
                  </div>

                  <div className="flex gap-2">
                    <Button type="submit" className="bg-green-600 hover:bg-green-700">
                      <CheckCircle className="w-4 h-4 mr-2" />
                      Confirm Deployment
                    </Button>
                    <Button 
                      type="button" 
                      variant="outline" 
                      onClick={() => setShowDeploymentForm(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                </form>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Badge className={
                  incident.deployment_decision.deployment_status === 'deployed' ? 'bg-green-100 text-green-800' :
                  incident.deployment_decision.deployment_status === 'monitoring' ? 'bg-blue-100 text-blue-800' :
                  'bg-gray-100 text-gray-800'
                }>
                  {incident.deployment_decision.deployment_status?.toUpperCase()}
                </Badge>
                {incident.deployment_decision.assigned_unit && (
                  <Badge variant="outline">
                    {incident.deployment_decision.assigned_unit.replace('_', ' ')}
                  </Badge>
                )}
              </div>

              <div className="text-sm text-gray-600">
                <div><strong>Decision by:</strong> {incident.deployment_decision.decided_by_name} ({incident.deployment_decision.decided_by_role})</div>
                <div><strong>Priority:</strong> {incident.deployment_decision.deployment_priority}</div>
                {incident.deployment_decision.decision_note && (
                  <div><strong>Note:</strong> {incident.deployment_decision.decision_note}</div>
                )}
                {incident.deployment_decision.deployed_at && (
                  <div><strong>Deployed:</strong> {formatDate(incident.deployment_decision.deployed_at)}</div>
                )}
                {incident.deployment_decision.deployment_outcome && (
                  <div><strong>Outcome:</strong> {incident.deployment_decision.deployment_outcome}</div>
                )}
              </div>

              <div className="flex gap-2">
                <Button 
                  variant="outline" 
                  size="sm"
                  onClick={() => window.open(
                    `https://www.google.com/maps?q=${incident.latitude},${incident.longitude}`,
                    '_blank'
                  )}
                >
                  <ExternalLink className="w-4 h-4 mr-2" />
                  View Location
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          Incident Command Dashboard
        </h1>
        <p className="text-gray-600">
          Review leader-confirmed incidents and make deployment decisions
        </p>
      </div>

      <div className="mb-6">
        <div className="flex gap-2">
          <Button
            variant={statusFilter === 'pending_deployment' ? 'default' : 'outline'}
            onClick={() => setStatusFilter('pending_deployment')}
          >
            <AlertTriangle className="w-4 h-4 mr-2" />
            Pending Deployment ({incidents.filter(i => !i.deployment_decision).length})
          </Button>
          <Button
            variant={statusFilter === 'deployed' ? 'default' : 'outline'}
            onClick={() => setStatusFilter('deployed')}
          >
            <CheckCircle className="w-4 h-4 mr-2" />
            Deployed ({incidents.filter(i => i.deployment_decision?.deployment_status === 'deployed').length})
          </Button>
          <Button
            variant={statusFilter === 'all' ? 'default' : 'outline'}
            onClick={() => setStatusFilter('all')}
          >
            <Users className="w-4 h-4 mr-2" />
            All Incidents
          </Button>
        </div>
      </div>

      {error && (
        <Alert className="mb-6 border-red-200 bg-red-50">
          <XCircle className="h-4 w-4 text-red-600" />
          <AlertDescription className="text-red-800">
            {error}
          </AlertDescription>
        </Alert>
      )}

      {loading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        </div>
      ) : incidents.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Shield className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">
              {statusFilter === 'pending_deployment' ? 'No Pending Deployments' : 'No Incidents Found'}
            </h3>
            <p className="text-gray-600">
              {statusFilter === 'pending_deployment' 
                ? 'All leader-confirmed incidents have been processed.' 
                : 'No incidents match the current filter.'}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div>
          <div className="mb-4 text-sm text-gray-600">
            Showing {incidents.length} incident{incidents.length !== 1 ? 's' : ''}
          </div>
          {incidents.map((incident) => (
            <DeploymentDecisionCard key={incident.report_id} incident={incident} />
          ))}
        </div>
      )}
    </div>
  );
};

export default CommanderDashboard;
